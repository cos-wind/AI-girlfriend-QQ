"""检索规划器：把事实源、原作设定和短期上下文压缩为一个小型 Context Pack。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atri_qq_bot.runtime.paths import PROMPT_DIR, PROJECT_ROOT

from .repository import RetrievedEntry, SemanticMemoryRepository
from .embeddings import OllamaEmbeddingClient


@dataclass(frozen=True)
class RetrievalSettings:
    """检索配置只在此处解释，避免记忆、人格和 WebUI 各自解析环境变量。"""

    enabled: bool
    database_path: Path
    max_context_chars: int = 1800
    lore_limit: int = 3
    memory_limit: int = 5
    vector_enabled: bool = False
    embedding_model: str = "bge-m3:latest"
    embedding_base_url: str = "http://127.0.0.1:11434"
    embedding_timeout_seconds: float = 2.0

    @classmethod
    def from_config(cls, memory_path: Path, config: Any | None) -> "RetrievalSettings":
        root = Path(memory_path).parent
        return cls(
            enabled=bool(getattr(config, "memory_retrieval_enabled", True)),
            database_path=Path(
                getattr(config, "memory_retrieval_path", root / "semantic_memory.sqlite3")
            ),
            max_context_chars=max(800, min(3000, int(getattr(config, "memory_retrieval_max_chars", 1800)))),
            lore_limit=max(1, min(5, int(getattr(config, "memory_retrieval_lore_limit", 3)))),
            memory_limit=max(2, min(8, int(getattr(config, "memory_retrieval_memory_limit", 5)))),
            # 向量索引只作为第二阶段能力：绝不在消息主线程自动加载 bge-m3。
            vector_enabled=bool(getattr(config, "memory_vector_enabled", False)),
            embedding_model=str(getattr(config, "memory_embedding_model", "bge-m3:latest")),
            embedding_base_url=str(
                getattr(config, "memory_embedding_base_url", "http://127.0.0.1:11434")
            ),
            embedding_timeout_seconds=float(
                getattr(config, "memory_embedding_timeout_seconds", 2.0)
            ),
        )


class ContextRetrievalPlanner:
    """唯一的检索接缝。

    输入是现有三层记忆 profile 和当前消息，输出仅为模型可读的紧凑文本；
    上游不需要知道 SQLite、FTS5 或未来的嵌入模型实现。
    """

    def __init__(self, settings: RetrievalSettings) -> None:
        self.settings = settings
        self.repository = SemanticMemoryRepository(settings.database_path)
        self._lore_indexed = False

    def build(self, profile: dict[str, Any], user_text: str) -> str:
        if not self.settings.enabled:
            return ""
        scope = str(profile.get("conversation_id") or "")
        if not scope:
            return ""
        self._sync_profile(scope, profile)
        self._ensure_lore_index()

        memories = self.repository.search(scope, user_text, self.settings.memory_limit)
        # 只有已有离线向量时才对查询加载 bge-m3；失败后仍使用 FTS5 结果。
        if self.settings.vector_enabled and self.repository.embedding_count(self.settings.embedding_model):
            try:
                vector = OllamaEmbeddingClient(
                    self.settings.embedding_model,
                    self.settings.embedding_base_url,
                    self.settings.embedding_timeout_seconds,
                ).embed(user_text)
                memories = _fuse(memories, self.repository.vector_search(
                    scope, self.settings.embedding_model, vector, self.settings.memory_limit
                ), self.settings.memory_limit)
            except Exception:
                pass
        lore = (
            self.repository.search("lore:atri", user_text, self.settings.lore_limit)
            if _looks_like_lore_question(user_text)
            else []
        )
        return self._render(profile, memories, lore)

    def status(self) -> dict[str, Any]:
        status = self.repository.status()
        status.update(
            {
                "enabled": self.settings.enabled,
                "vector_enabled": self.settings.vector_enabled,
                "embedding_model": self.settings.embedding_model,
                "mode": "FTS5 + 可选 bge-m3 向量二次召回",
            }
        )
        return status

    def _sync_profile(self, scope: str, profile: dict[str, Any]) -> None:
        structured = profile.get("structured_memory") or {}
        entries: list[dict[str, Any]] = []
        for layer_name, importance in (("l1", 0.95), ("l2", 0.72), ("candidates", 0.45)):
            for item in list(structured.get(layer_name) or []):
                if not isinstance(item, dict) or str(item.get("state") or "") == "sleeping":
                    continue
                value = str(item.get("value") or "").strip()
                if not value:
                    continue
                entries.append(
                    {
                        "layer": layer_name,
                        "title": str(item.get("key") or item.get("category") or "记忆"),
                        "content": value,
                        "importance": max(0.0, min(1.0, float(item.get("confidence") or importance))),
                        "updated_at": item.get("updated_at") or item.get("created_at") or time.time(),
                        "metadata": {"category": item.get("category"), "state": item.get("state")},
                    }
                )
        self.repository.replace_scope_source(scope, "user_profile", entries)

    def _ensure_lore_index(self) -> None:
        if self._lore_indexed:
            return
        entries: list[dict[str, Any]] = []
        # 这两份是已整理后的项目人格/原作设定；不把单一提示词作为真相来源。
        for path in (PROMPT_DIR / "lore.md", PROMPT_DIR / "atri_persona.md"):
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            entries.extend(_markdown_chunks(path.name, text))
        self.repository.replace_scope_source("lore:atri", "project_lore", entries)
        self._lore_indexed = True

    def _render(
        self,
        profile: dict[str, Any],
        memories: list[RetrievedEntry],
        lore: list[RetrievedEntry],
    ) -> str:
        lines = [
            "相处细节：先接住当前话题；只在确实相关时自然带出，不要说自己在读取记忆，也不要说调用或记录记忆。",
            "可以轻轻嘴硬一句“哼，我才不是特意记的”；记不准就坦白，不要补造细节。",
        ]
        affection = str(profile.get("affection_state") or "").strip()
        if affection:
            # 沿用旧上下文的自然表述，避免下游人格提示和既有测试语义变化。
            lines.append("你现在对用户的自然感觉：" + affection)
        if str(profile.get("conversation_id") or "").startswith("group:"):
            activity = str(profile.get("group_activity_state") or "").strip()
            if activity:
                lines.append("群聊气氛：" + activity)

        used = 0
        memory_lines: list[str] = []
        for entry in memories:
            line = _memory_line(entry)
            if line and len(line) + used <= self.settings.max_context_chars * 0.56:
                memory_lines.append(line)
                used += len(line)
        if memory_lines:
            lines.append("你知道的用户信息（与当前话题相关）：" + "；".join(memory_lines))

        lore_lines: list[str] = []
        for entry in lore:
            text = _truncate(entry.content, 420)
            if text and len(text) + used <= self.settings.max_context_chars:
                lore_lines.append(f"{entry.title}：{text}")
                used += len(text)
        if lore_lines:
            lines.append(
                "原作设定参考（仅回答涉及原作的问题；不确定或资料冲突时说明不确定，禁止补造）："
                + "\n".join(lore_lines)
            )

        interval = str(profile.get("personal_question_interval") or "五到八轮")
        lines.append(f"主动了解用户要克制：自然聊天中每{interval}最多问一个个人问题。")
        return "\n".join(lines)


def _markdown_chunks(name: str, text: str) -> list[dict[str, Any]]:
    title = name.rsplit(".", 1)[0]
    current_title = title
    buffer: list[str] = []
    chunks: list[dict[str, Any]] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        if not content:
            return
        for index in range(0, len(content), 700):
            piece = content[index : index + 700].strip()
            if piece:
                chunks.append(
                    {
                        "layer": "lore",
                        "title": current_title,
                        "content": piece,
                        "importance": 0.9,
                        "updated_at": 0,
                        "metadata": {"document": name},
                    }
                )

    for raw in text.splitlines():
        heading = re.match(r"^#{1,4}\s+(.+)$", raw.strip())
        if heading:
            flush()
            buffer.clear()
            current_title = heading.group(1).strip()
        elif raw.strip():
            buffer.append(raw.strip())
    flush()
    return chunks


def _looks_like_lore_question(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    needles = (
        "亚托莉", "atri", "my dear moment", "夏生", "诗菜", "龙司", "水菜萌",
        "高性能", "yhn", "海底", "打捞", "45天", "原作", "剧情", "设定", "动画", "gal",
    )
    return any(needle in value for needle in needles)


def _memory_line(entry: RetrievedEntry) -> str:
    if not entry.content:
        return ""
    if entry.layer == "candidates":
        return f"可能：{entry.title}—{entry.content}"
    return f"{entry.title}—{entry.content}"


def _truncate(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _fuse(
    lexical: list[RetrievedEntry], vector: list[RetrievedEntry], limit: int
) -> list[RetrievedEntry]:
    """RRF 融合，避免单一关键词或单一向量分数主导召回。"""

    scored: dict[str, tuple[RetrievedEntry, float]] = {}
    for rank, entry in enumerate(lexical, start=1):
        scored[entry.entry_id] = (entry, 1.0 / (60 + rank))
    for rank, entry in enumerate(vector, start=1):
        previous = scored.get(entry.entry_id)
        value = 1.0 / (60 + rank) + (previous[1] if previous else 0.0)
        scored[entry.entry_id] = (entry, value)
    return [pair[0] for pair in sorted(scored.values(), key=lambda pair: pair[1], reverse=True)[:limit]]
