from __future__ import annotations

from .support import MemoryMixin


class MemoryStateMixin(MemoryMixin):
    def __init__(self, path: Path, config: Any | None = None) -> None:
        self.path = path
        # WebUI 通过“临时文件 + os.replace”保存。仅比较 mtime/size 时，两个等长
        # 内容在部分 Windows 文件系统的同一时间粒度内可能被误判成未变化；加入
        # 文件标识与 ctime 后，消息进程能可靠接住 WebUI 的最新人工编辑。
        self._loaded_file_state: tuple[int, int, int, int] | None = None
        self._data = self._load()
        self._loaded_file_state = self._current_file_state()
        self._session_l3: dict[str, list[dict[str, Any]]] = {}
        self._save_retry_after = 0.0
        self._save_failure_count = 0
        self._memory_state_lock = threading.RLock()
        # 检索器是可选的旁路；即使 SQLite 文件损坏，原 JSON 记忆仍能正常工作。
        self._retrieval = ContextRetrievalPlanner(
            RetrievalSettings.from_config(path, config)
        )
        self._memory_worker = MemoryExtractionWorker(
            self._apply_extraction_result,
            # 只有正式应用传入 BotConfig 时才启动后台线程。测试、迁移脚本和
            # 离线检查直接构造 Store，仍保留同步规则提取，但不会留下异步回写
            # 去覆盖随后发生的 WebUI 人工编辑。
            enabled=config is not None
            and bool(getattr(config, "memory_extraction_enabled", True)),
            # 直接创建 UserMemoryStore（测试、迁移脚本、离线修复）默认不应
            # 意外拉起本地大模型；正式运行由 load_config 明确打开此开关。
            llm_enabled=bool(getattr(config, "memory_extraction_llm_enabled", False)),
            model=str(getattr(config, "memory_extraction_model", "qwen3:4b-instruct")),
            base_url=str(getattr(config, "memory_extraction_base_url", "http://127.0.0.1:11434")),
            api_key=getattr(config, "memory_extraction_api_key", None),
            timeout_seconds=float(getattr(config, "memory_extraction_timeout_seconds", 10.0)),
            cooldown_seconds=float(getattr(config, "memory_extraction_cooldown_seconds", 45.0)),
        )
        self._backfill_thread: threading.Thread | None = None
        self._memory_backfill_max_conversations = int(
            getattr(config, "memory_backfill_max_conversations", 250) or 250
        )
        if bool(getattr(config, "memory_backfill_enabled", False)):
            self._backfill_thread = threading.Thread(
                target=self._backfill_history_profiles,
                name="atri-memory-backfill",
                daemon=True,
            )
            self._backfill_thread.start()

    def _conversation(self, conversation_id: str, save: bool = True) -> dict[str, Any]:
        self._reload_if_changed()
        conversations = self._data.setdefault("conversations", {})
        if conversation_id not in conversations:
            conversations[conversation_id] = {}
            if save:
                self._save()
        return conversations[conversation_id]

    def _current_file_state(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino

    def _reload_if_changed(self) -> None:
        current_state = self._current_file_state()
        if current_state == self._loaded_file_state:
            return
        self._data = self._load()
        self._loaded_file_state = self._current_file_state()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": MEMORY_VERSION, "conversations": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": MEMORY_VERSION, "conversations": {}}
        if not isinstance(data, dict):
            return {"version": MEMORY_VERSION, "conversations": {}}
        data["version"] = max(int(data.get("version", 1) or 1), MEMORY_VERSION)
        data.setdefault("conversations", {})
        return data

    def _save(self) -> bool:
        """尽量持久化记忆，但绝不让持久化异常中断当前回复。

        旧实现先用 ``json.dumps`` 把整个记忆树拼成一个大字符串，再一次性写入
        临时文件。系统内存紧张时，这个额外的字符串缓冲区可能触发
        ``MemoryError``，异常会沿着消息处理链路冒泡，表现为“连接正常但不回复”。

        这里改为流式 ``json.dump`` 写临时文件，并对内存不足和文件 I/O 异常做
        有限退避。临时文件只有在完整写入后才替换正式文件，因此不会留下半截
        users.json；内存恢复后下一次保存会自动恢复。
        """
        now = time.monotonic()
        if now < self._save_retry_after:
            return False

        tmp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 直接向临时文件写入，避免额外创建完整 JSON 字符串。
            with tmp_path.open("w", encoding="utf-8") as stream:
                json.dump(self._data, stream, ensure_ascii=False, indent=2)
                stream.flush()
            for attempt in range(4):
                try:
                    tmp_path.replace(self.path)
                    break
                except PermissionError:
                    if attempt >= 3:
                        raise
                    time.sleep(0.025 * (attempt + 1))
        except MemoryError:
            self._save_failure_count += 1
            delay = min(
                SAVE_RETRY_MAX_SECONDS,
                SAVE_RETRY_MIN_SECONDS * (2 ** min(self._save_failure_count - 1, 4)),
            )
            self._save_retry_after = now + delay
            LOGGER.warning(
                "记忆保存暂缓：系统内存不足，当前回复继续执行；将在 %.1f 秒后重试",
                delay,
            )
            return False
        except (OSError, TypeError, ValueError) as exc:
            self._save_failure_count += 1
            delay = min(
                SAVE_RETRY_MAX_SECONDS,
                SAVE_RETRY_MIN_SECONDS * (2 ** min(self._save_failure_count - 1, 4)),
            )
            self._save_retry_after = now + delay
            LOGGER.warning(
                "记忆保存暂缓：文件写入失败（%s），当前回复继续执行；将在 %.1f 秒后重试",
                exc,
                delay,
            )
            return False
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        self._loaded_file_state = self._current_file_state()
        self._save_failure_count = 0
        self._save_retry_after = 0.0
        return True
