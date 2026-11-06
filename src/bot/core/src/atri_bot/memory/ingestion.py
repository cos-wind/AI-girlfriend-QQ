"""后台记忆摄取。

这个 Module 只负责把用户消息转换成可审计的结构化操作，不直接参与回复。
调用者把请求放入有界队列后即可继续回复；模型不可用、超时或输出不合法时，
调用者仍可以使用确定性提取结果，绝不会让记忆异常阻断 OneBot 消息链路。
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atri_bot.prompting import load_prompt
from atri_bot.memory.identity import explicit_identity, identity_key
from atri_bot.memory.evidence import assertion_spans, evidence_span
from atri_bot.memory.rule_common import EVENT_HINTS, TIME_HINT_PATTERN, IMPLICIT_INTEREST_HINTS
from atri_shared.runtime.inference_lock import InferenceResourceBusyError, inference_resource_lease_sync


MEMORY_SIGNAL_HINTS = (
    "我叫", "叫我", "我是", "我的", "我喜欢", "我爱", "我讨厌", "不喜欢",
    "平时", "经常", "通常", "每天", "最近", "这段时间", "一直在", "正在",
    "生日", "明天", "后天", "考试", "面试", "会议", "项目", "以后", "不要",
    "别", "只要", "习惯", "来自", "学习", "工作", "准备", "玩", "看", "追",
)
_SENSITIVE_MARKERS = (
    "密码", "验证码", "身份证", "银行卡", "私钥", "token", "cookie", "口令",
)
_ALLOWED_L1 = {"profile_fact", "interest", "preference", "habit", "communication_style"}
_ALLOWED_L2 = {"event", "schedule", "important_interaction"}
_OPERATION_NAMES = {"ADD", "UPDATE", "DELETE", "NOOP"}


@dataclass(frozen=True)
class MemoryExtractionRequest:
    conversation_id: str
    subject_id: str
    text: str
    recent_context: tuple[str, ...] = ()
    known_memory: tuple[str, ...] = ()
    now: float = field(default_factory=time.time)
    visibility: str = "private"
    source_context: str | None = None
    scope_kind: str = "person"


@dataclass(frozen=True)
class MemoryExtractionResult:
    request: MemoryExtractionRequest
    operations: tuple[dict[str, Any], ...]
    model_used: str = "deterministic"
    error: str = ""


def should_enqueue_memory(text: str) -> bool:
    value = str(text or "").strip()
    if not value or len(value) < 4:
        return False
    # 不能只靠“我喜欢/生日”等关键词：用户的兴趣、习惯经常通过连续
    # 追问、举例和上下文间接表达。真正的短消息由长度和噪声门槛过滤，
    # 进入后台后仍由提示词决定“明确记忆 / 候选 / 不记录”。
    return value not in {"哈哈哈哈", "哈哈哈", "呵呵", "嗯嗯", "哦哦", "好的", "收到", "谢谢", "行行行"}


def deterministic_operations(
    text: str,
    *,
    now: float,
    visibility: str,
    source_context: str | None,
    scope_kind: str,
) -> list[dict[str, Any]]:
    """处理高置信、可解释的显式表达；复杂语义交给可选本地模型。"""
    operations: list[dict[str, Any]] = []
    style_spans: list[tuple[str, int, int]] = []

    def add(layer, category, key, fact, evidence, confidence=.8, source_type="explicit"):
        fact = _clean_value(fact)
        if not fact or _unsafe_value(fact) or _unsafe_value(evidence):
            return
        operations.append({
            "operation": "ADD", "layer": layer, "category": category,
            "key": key, "value": fact, "confidence": confidence,
            "source_type": source_type, "evidence": evidence,
            "visibility": visibility, "source_context": source_context,
            "created_at": now, "updated_at": now,
            "promote": (source_type == "explicit" and visibility == "private"
                        and category in {"profile_fact", "preference"}),
        })

    for clause, start, end in assertion_spans(str(text or "")):
        # A member's self report belongs to that member, never to the group.
        if scope_kind == "group":
            if (re.match(r"^(?:本群|我们群|群里|大家|我们)", clause)
                    and TIME_HINT_PATTERN.search(clause)
                    and any(h in clause for h in EVENT_HINTS)):
                add("L2", "event", _event_key(clause), clause, clause)
            continue
        nickname = re.fullmatch(r"(?:我叫|叫我|以后叫我|你可以叫我)\s*([^，。！？!?]{1,16})", clause)
        if nickname and "亚托莉" not in nickname[1]:
            add("L1", "profile_fact", "称呼", nickname[1], clause)
        birthday = re.fullmatch(r"我(?:的)?生日(?:是|在|：|:)?\s*((?:\d{4}年)?\d{1,2}月\d{1,2}[日号]?|\d{1,2}[./-]\d{1,2})", clause)
        if birthday:
            add("L1", "profile_fact", "生日", birthday[1], clause)
        identity = explicit_identity(clause)
        if identity:
            add("L1", "profile_fact", identity_key(identity), identity, clause)

        # One match chooses one label. The old generic regex also matched
        # "玩原神" after the specific regex had already extracted "原神".
        preference = re.fullmatch(
            r"(?:我(?:真的|很|超|也|平时|经常|常常|一直|其实)*|(?=不喝|不吃|不再喜欢|不喜欢|不爱|讨厌))"
            r"(不再喜欢|不喜欢|不爱|讨厌|不喝|不吃|喜欢|爱)(吃|喝|看|玩|做)?\s*(.{1,30})", clause)
        if preference:
            polarity, activity, fact = preference.groups()
            fact = re.sub(r"[了啦呀呢吧]$", "", fact).strip()
            label = ("讨厌" if polarity in {"不再喜欢", "不喜欢", "不爱", "讨厌", "不喝", "不吃"}
                     else "喜欢的食物" if activity in {"吃", "喝"}
                     else "兴趣爱好" if activity else "偏好")
            if _valid_fact(fact):
                add("L1", "preference", f"{label}:{fact}", fact, clause)
        habit = re.fullmatch(r"我(?:平时|经常|常常|一般|每天|习惯|通常)\s*(?:会|都|在)?\s*(.{2,30})", clause)
        if habit and not preference and _valid_fact(habit[1]):
            add("L1", "habit", "日常习惯", habit[1], clause, .75)
        recent = re.fullmatch(r"(?:我)?(?:最近|这段时间|最近几天)(?:一直|总是|都在|在)?\s*(玩|看|追|学习|准备|研究|做|用)\s*(.{1,24})", clause)
        if recent and _valid_fact(recent[2]):
            add("L1", "interest", f"近期{recent[1]}", recent[2], clause, .68, "implicit")
        if (re.match(r"^(?:我(?!们|朋友|同学|同事|的)|(?:今晚|今天|明天|周末)(?:准备|打算|计划|继续|要|想|在))", clause)
                and not preference and not recent):
            for word in IMPLICIT_INTEREST_HINTS:
                if word in clause:
                    add("L1", "interest", f"兴趣:{word}", word, clause, .6, "implicit")

        style_terms = ("别发日语", "不要发日语", "不准发日语", "别用日语", "不要用日语",
                       "别发外语", "不要发外语", "只说中文", "讲中文", "正常中文",
                       "别学我说话", "不要学我说话", "别复读", "不要复读",
                       "别主动发消息", "不要主动发消息", "没事别发消息", "少主动",
                       "别刷屏", "不要刷屏", "不要套话", "有逻辑")
        if (re.match(r"^(?:以后|之后|平时|请|别|不要|不准|只|讲|正常|没事|少)", clause)
                and (any(w in clause for w in style_terms) or (
                    any(w in clause for w in ("短句", "直接", "别绕"))
                    and any(w in clause for w in ("回复", "回答", "说话"))))):
            style_spans.append((clause, start, end))
        event_body = clause
        while match := TIME_HINT_PATTERN.match(event_body):
            event_body = event_body[match.end():].lstrip()
        if (TIME_HINT_PATTERN.search(clause) and any(h in clause for h in EVENT_HINTS)
                and re.match(r"^(?:我(?!们|朋友|同学|同事|的(?:朋友|同学|同事|家人))|是我的|有|要|会|准备|计划|打算|去|参加|生日|考试|面试|开会|出差|旅行|复习|报名)", event_body)):
            add("L2", "event", _event_key(clause), clause, clause)
    if style_spans:
        # Keep all explicit requirements in one message as one claim, so the
        # foreground and background passes cannot confirm different fragments.
        evidence = text[style_spans[0][1]:style_spans[-1][2]]
        add("L1", "communication_style", "回复方式",
            "，".join(_style_rule_value(clause) for clause, _, _ in style_spans), evidence)
    return operations


def _style_rule_value(text: str) -> str:
    # Keep the user's actual requirement; "short replies" does not imply
    # additional preferences, and "do not initiate" must not become "less often".
    return _clean_value(text)


class MemoryExtractionWorker:
    """有界、单线程的后台提取队列。"""

    def __init__(
        self,
        callback: Callable[[MemoryExtractionResult], None],
        *,
        enabled: bool = True,
        llm_enabled: bool = False,
        model: str = "qwen3:4b-instruct",
        base_url: str = "http://127.0.0.1:11434",
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        cooldown_seconds: float = 15.0,
        prompt_path: Path | None = None,
    ) -> None:
        self.callback = callback
        self.enabled = bool(enabled)
        self.llm_enabled = bool(llm_enabled)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "ollama")
        self.timeout_seconds = max(2.0, min(30.0, float(timeout_seconds)))
        self.cooldown_seconds = max(3.0, min(300.0, float(cooldown_seconds)))
        self.prompt_path = prompt_path
        self._queue: queue.Queue[MemoryExtractionRequest] = queue.Queue(maxsize=256)
        self._pending_conversations: set[str] = set()
        self._pending_lock = threading.Lock()
        self._last_model_at: dict[str, float] = {}
        # 模型增强只是旁路能力；连续超时后短暂熔断，避免画像线程反复占用网络、CPU 和连接数。
        self._model_failure_count = 0
        self._model_disabled_until = 0.0
        self._model_last_error = ""
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def submit(self, request: MemoryExtractionRequest) -> bool:
        # 提取任务进入有界队列后立即返回；当前回复链路不等待 LLM 记忆提取。
        # 同一会话只允许一个 pending 任务，避免群聊高峰把后台队列堆满。
        if not self.enabled or not should_enqueue_memory(request.text):
            return False
        self._ensure_started()
        with self._pending_lock:
            # 同一会话只保留一个在途任务，避免群聊高峰把后台队列堆满。
            if request.conversation_id in self._pending_conversations:
                return False
            self._pending_conversations.add(request.conversation_id)
        try:
            self._queue.put_nowait(request)
            return True
        except queue.Full:
            with self._pending_lock:
                self._pending_conversations.discard(request.conversation_id)
            return False

    def status(self) -> dict[str, Any]:
        """返回轻量运行状态，供日志/调试面板查看，不触发模型加载。"""
        thread = self._thread
        return {
            "enabled": self.enabled,
            "llm_enabled": self.llm_enabled,
            "model": self.model,
            "queued": self._queue.qsize(),
            "running": bool(thread and thread.is_alive()),
            "last_model_at": max(self._last_model_at.values(), default=0.0),
            "model_disabled_until": self._model_disabled_until,
            "model_failure_count": self._model_failure_count,
            "model_last_error": self._model_last_error,
        }

    def _ensure_started(self) -> None:
        # 采用惰性单线程：没有需要提取的消息时不占线程，开始工作后保持一个
        # 顺序消费者，避免同一用户的画像更新出现竞态。
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="atri-memory-extractor",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            try:
                operations = deterministic_operations(
                    request.text,
                    now=request.now,
                    visibility=request.visibility,
                    source_context=request.source_context,
                    scope_kind=request.scope_kind,
                )
                model_used = "deterministic"
                error = ""
                if self._can_use_model(request):
                    try:
                        if self._uses_local_ollama():
                            # 后台记忆不能与视觉同时加载本地大模型。拿不到锁时
                            # 直接保留确定性 L1/L2 提取，不阻塞也不影响回复链路。
                            with inference_resource_lease_sync(
                                f"memory:{self.model}",
                                timeout_seconds=0.0,
                            ):
                                try:
                                    operations.extend(self._model_operations(request))
                                finally:
                                    self._unload_local_model()
                        else:
                            operations.extend(self._model_operations(request))
                        model_used = self.model
                        self._model_failure_count = 0
                        self._model_last_error = ""
                    except InferenceResourceBusyError:
                        # 这是预期的资源退让，不是模型故障；规则提取结果照常入库，
                        # 下一条满足冷却条件的消息仍可尝试模型增强。
                        pass
                    except Exception as exc:  # pragma: no cover - network/model dependent
                        error = str(exc)[:240]
                        self._model_failure_count += 1
                        self._model_last_error = error
                        if self._model_failure_count >= 2:
                            # 五分钟后自动试探一次；此期间仍保留规则提取，保证画像继续增长。
                            self._model_disabled_until = time.time() + 300.0
                operations = _deduplicate_operations(operations)
                # 即使模型失败也回调一次，让主服务记录诊断日志，而不是静默丢失。
                if operations or error:
                    self.callback(MemoryExtractionResult(request, tuple(operations), model_used, error))
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                self.callback(MemoryExtractionResult(request, (), "deterministic", str(exc)[:240]))
            finally:
                with self._pending_lock:
                    self._pending_conversations.discard(request.conversation_id)
                self._queue.task_done()

    def _can_use_model(self, request: MemoryExtractionRequest) -> bool:
        if not self.llm_enabled:
            return False
        now = time.time()
        if now < self._model_disabled_until:
            return False
        previous = self._last_model_at.get(request.conversation_id, 0.0)
        if now - previous < self.cooldown_seconds:
            return False
        self._last_model_at[request.conversation_id] = now
        return True

    def _model_operations(self, request: MemoryExtractionRequest) -> list[dict[str, Any]]:
        prompt = load_prompt("memory_extraction")
        context = "\n".join(request.recent_context[-6:])[:1200]
        known = "；".join(request.known_memory[-12:])[:1000]
        user_content = (
            f"作用域：{request.scope_kind}\n"
            f"记忆主体：{request.subject_id}\n"
            f"可见范围：{request.visibility}\n"
            f"已有相关记忆：{known or '无'}\n"
            f"最近消息：{context or request.text[:1200]}\n"
            f"新消息：{request.text[:1200]}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 260,
            "stream": False,
        }
        is_ollama = "127.0.0.1:11434" in self.base_url or "localhost:11434" in self.base_url
        is_deepseek_v4 = (
            "api.deepseek.com" in self.base_url.casefold()
            and self.model.casefold() in {"deepseek-v4-flash", "deepseek-v4-pro"}
        )
        if is_ollama:
            # Ollama 支持这两个扩展字段；云端 OpenAI 兼容服务不应收到 keep_alive。
            payload["response_format"] = {"type": "json_object"}
            payload["keep_alive"] = "0"
        if is_deepseek_v4:
            # 画像提取只需要结构化事实，不需要深度思考链，避免后台任务拖慢或超时。
            payload["thinking"] = {"type": "disabled"}
        endpoint = (
            self.base_url + "/chat/completions"
            if self.base_url.endswith("/v1")
            else self.base_url + "/v1/chat/completions"
        )
        request_http = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urlopen(request_http, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return _normalise_model_operations(content, request)

    def _uses_local_ollama(self) -> bool:
        lowered = self.base_url.casefold()
        return bool(
            "127.0.0.1:11434" in lowered
            or "localhost:11434" in lowered
            or "[::1]:11434" in lowered
        )

    def _unload_local_model(self) -> None:
        """显式卸载 OpenAI 兼容接口可能忽略 keep_alive 的本地模型。"""
        native_base = re.sub(r"/v1/?$", "", self.base_url.rstrip("/"))
        payload = json.dumps(
            {"model": self.model, "keep_alive": 0},
            ensure_ascii=False,
        ).encode("utf-8")
        request_http = Request(
            native_base + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(
                request_http,
                timeout=min(5.0, self.timeout_seconds),
            ):
                pass
        except (HTTPError, URLError, TimeoutError, OSError):
            pass


def _normalise_model_operations(content: Any, request: MemoryExtractionRequest) -> list[dict[str, Any]]:
    if isinstance(content, str):
        # 兼容模型把 JSON 放进 ```json ... ``` 或在前后附带一句说明的情况。
        fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", content, flags=re.I | re.S)
        if fenced:
            content = fenced.group(1)
        else:
            match = re.search(r"(\{.*\}|\[.*\])", content, flags=re.S)
            if match:
                content = match.group(1)
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (TypeError, json.JSONDecodeError):
        return []
    raw_operations = data.get("operations", []) if isinstance(data, dict) else data
    if not isinstance(raw_operations, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in raw_operations[:8]:
        if not isinstance(raw, dict):
            continue
        operation = str(raw.get("operation") or "NOOP").upper()
        layer = str(raw.get("layer") or "").upper()
        category = str(raw.get("category") or "").strip()
        if operation not in _OPERATION_NAMES or operation == "NOOP":
            continue
        allowed = _ALLOWED_L1 if layer == "L1" else _ALLOWED_L2 if layer == "L2" else set()
        if category not in allowed:
            continue
        key = _clean_value(raw.get("key"))[:80]
        value = _clean_value(raw.get("value"))[:120]
        if not key or (operation != "DELETE" and not value) or _unsafe_value(value):
            continue
        # The host owns identity/scope. Evidence must resolve to the new message;
        # summaries, previous assistant replies and model-written quotations are
        # not independent evidence. Model-only interpretations need review.
        evidence = raw.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 180:
            continue
        evidence = evidence.strip()
        span = evidence_span(request.text, evidence, request.scope_kind)
        if (span is None or _unsafe_value(evidence) or operation == "DELETE"
                or raw.get("subject_id", request.subject_id) != request.subject_id
                or (request.scope_kind == "group" and category == "profile_fact")):
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.6))))
        except (TypeError, ValueError):
            confidence = 0.6
        result.append(
            {
                "operation": operation,
                "layer": layer,
                "category": category,
                "key": key,
                "value": value,
                "confidence": confidence,
                "source_type": "model",
                "evidence": evidence,
                "evidence_start": span[0],
                "evidence_end": span[1],
                "subject_id": request.subject_id,
                "visibility": request.visibility,
                "source_context": request.source_context,
                "created_at": request.now,
                "updated_at": request.now,
                "promote": False,
                "candidate_only": True,
            }
        )
    return result


def _deduplicate_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for operation in operations:
        key = (
            str(operation.get("layer")),
            str(operation.get("category")),
            str(operation.get("key")),
        )
        previous = result.get(key)
        if previous is None or (previous.get("source_type") != "explicit"
                and (operation.get("source_type") == "explicit"
                     or float(operation.get("confidence", 0.0)) >= float(previous.get("confidence", 0.0)))):
            result[key] = operation
    return list(result.values())


def _event_key(text: str) -> str:
    time_match = re.search(r"今天|明天|后天|大后天|\d{1,2}月\d{1,2}|\d{1,2}[点:：]", text)
    event = next((hint for hint in ("生日", "考试", "面试", "会议", "项目", "截止", "旅行") if hint in text), "事件")
    return f"{time_match.group(0) if time_match else '持续'}:{event}"


def _clean_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ，。！？!?~～：:")


def _valid_fact(value: str) -> bool:
    return bool(value) and len(value) <= 30 and not any(marker in value for marker in ("你", "亚托莉", "这个", "那个", "什么", "…", "..."))


def _unsafe_value(value: str) -> bool:
    lower = value.lower()
    return any(marker.lower() in lower for marker in _SENSITIVE_MARKERS)


__all__ = [
    "MemoryExtractionRequest",
    "MemoryExtractionResult",
    "MemoryExtractionWorker",
    "deterministic_operations",
    "should_enqueue_memory",
]
