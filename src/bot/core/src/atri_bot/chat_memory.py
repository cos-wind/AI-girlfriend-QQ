"""Lightweight desktop archive; no reply engine or model starts at import time."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from atri_bot.knowledge import KnowledgeStore
from atri_bot.knowledge import ingestion
from atri_bot.knowledge.retrieval import retrieve
from atri_bot.knowledge.store import LOCAL_TIME, can_retry_source

SCOPE = "desktop:owner"
MAX_MESSAGE = 200_000
MAX_ATTACHMENTS = 50
MAX_UPLOAD_BYTES = 240_000_000  # Combined, before base64 encoding; each original <=80MB.


@dataclass(frozen=True)
class ChatAttachment:
    filename: str
    data: bytes = field(repr=False)


def bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit * 3 // 4] + "\n[本次上下文节选，完整原文保存在本地]\n" + text[-limit // 4:]


def query_day(query: str, now: datetime | None = None) -> str:
    today = (now or datetime.now(LOCAL_TIME)).astimezone(LOCAL_TIME).date()
    explicit = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", query)
    if explicit:
        try:
            return KnowledgeStore.validate_day(explicit[1])
        except ValueError:
            return ""
    for word, delta in (("大前天", 3), ("前天", 2), ("昨天", 1), ("今天", 0)):
        if word in query:
            return (today - timedelta(days=delta)).isoformat()
    return ""


@dataclass
class PreparedTurn:
    store: KnowledgeStore
    request_id: str
    context: str = ""
    attachment_ids: list[str] = field(default_factory=list)
    cached_reply: str = ""
    config: Any = None


class DesktopChatMemory:
    def store_for(self, config: Any) -> KnowledgeStore:
        return KnowledgeStore.for_memory(Path(config.memory_path))

    def prepare(self, config: Any, text: str, attachments: list[ChatAttachment], request_id: str, *, background=False, recall=True) -> PreparedTurn:
        store = self.store_for(config)
        # Look up before inserting the current message so it cannot recall itself.
        fingerprint = hashlib.sha256(text.encode("utf-8"))
        for attachment in attachments:
            fingerprint.update(json.dumps(attachment.filename, ensure_ascii=False).encode("utf-8"))
            fingerprint.update(hashlib.sha256(attachment.data).digest())
        fingerprint_value = fingerprint.hexdigest()
        previous = store.by_external_id(SCOPE, f"desktop:user:{request_id}")
        if previous and previous["metadata"].get("fingerprint") != fingerprint_value:
            raise ValueError("消息重试内容已变化，请重新发送")
        cached = store.by_external_id(SCOPE, f"desktop:assistant:{request_id}")
        context = self._recall(store, config, text, request_id) if recall else ''
        urls = list(dict.fromkeys(re.findall(r'https?://[^\s<>"\x27`]+', text)))[:max(0, min(10, MAX_ATTACHMENTS-len(attachments)))] if len(text) <= 8000 and '```' not in text else []
        urls = [url.rstrip('。，；！？、）)]}') for url in urls]
        user = store.create(SCOPE, text, title="与亚托莉的对话", kind="message",
                            external_id=f"desktop:user:{request_id}",
                            metadata={"fingerprint": fingerprint_value, "attachment_count": len(attachments)+len(urls),
                                      "request_id": request_id})
        prepared = PreparedTurn(store, request_id, context, cached_reply=cached["text"] if cached else "", config=config)
        # Always archive originals before attempting parsing or the cloud request.
        for index, attachment in enumerate(attachments):
            item = store.create(SCOPE, "", title=attachment.filename, kind="material",
                                filename=attachment.filename, raw=attachment.data, enqueue=True,
                                occurred_at=user["occurred_at"], coverage="pending_parse",
                                locator=f"desktop:attachment:{request_id}:{index}",
                                external_id=f"desktop:attachment:{request_id}:{index}",
                                metadata={"message_source_id": user["id"]})
            prepared.attachment_ids.append(item["id"])
        for index, url in enumerate(urls, start=len(attachments)):
            item = store.create(SCOPE, '', title=url[:200], kind='material', enqueue=True,
                occurred_at=user['occurred_at'], coverage='pending_parse', locator=url,
                external_id=f'desktop:attachment:{request_id}:{index}',
                metadata={'message_source_id': user['id'], 'import_url': True})
            prepared.attachment_ids.append(item['id'])
        # Uploaded media must be read before composing this turn's answer.
        # Plain chat still skips media processing entirely.
        if attachments and not background:
            from atri_bot.toolbox import TEXT_EXTENSIONS, DOC_EXTENSIONS, SHEET_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
            for attachment, source_id in zip(attachments, prepared.attachment_ids):
                ext = Path(attachment.filename).suffix.lower()
                media_ready = bool(getattr(config, "toolbox_vision_enabled", False) or getattr(config, "toolbox_ocr_enabled", False))
                if ext in (TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS) or (media_ready and ext in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)):
                    ingestion.run_pending(store, config, max_jobs=1, source_id=source_id)
                    # An already active archive worker may own this source's lease.
                    deadline = time.monotonic() + 75
                    while store.get(SCOPE, source_id)["job_status"] == "running" and time.monotonic() < deadline:
                        time.sleep(0.1)
        ingestion.start_pending(store, config)
        current = []
        matched = store.search(SCOPE, text[:1000], limit=30) if prepared.attachment_ids else []
        for source_id in prepared.attachment_ids:
            item = store.get(SCOPE, source_id)
            current.append({"id": source_id, "filename": item["filename"], "revision": item["revision"],
                            "status": item["job_status"], "coverage": item["coverage"],
                            "error": item["job_error"], "excerpt": bounded(item["text"], 2500),
                            "analysis": item["metadata"].get("analysis", {}),
                            "relevant_blocks": [{"anchor": h["anchor"], "text": h["content"]}
                                                for h in matched if h["id"] == source_id][:3]})
        if current:
            prepared.context += "\n当前附件（正文仅节选；pending/running 表示尚未读到正文，failed 表示解析失败）：\n" + json.dumps(current, ensure_ascii=False)
        return prepared

    def complete(self, prepared: PreparedTurn, reply: str) -> None:
        prepared.store.create(SCOPE, reply, kind="assistant", title="亚托莉回复",
                              external_id=f"desktop:assistant:{prepared.request_id}")
        if prepared.config is not None:
            ingestion.start_pending(prepared.store, prepared.config)

    def status(self, config: Any, request_id: str, *, retry_index: int | None = None) -> list[dict[str, Any]]:
        store = self.store_for(config)
        if not store.path.exists():
            return []
        user = store.by_external_id(SCOPE, f"desktop:user:{request_id}")
        if not user:
            return []
        count = min(MAX_ATTACHMENTS, int(user["metadata"].get("attachment_count", 0)))
        if retry_index is not None and not 0 <= retry_index < count:
            raise ValueError("找不到这条消息的附件")
        result = []
        for index in range(count):
            item = store.by_external_id(SCOPE, f"desktop:attachment:{request_id}:{index}")
            if not item:
                continue
            if index == retry_index:
                store.retry(SCOPE, item["id"])
                item = store.get(SCOPE, item["id"])
            elapsed = max(0, time.time()-item['metadata'].get('parse_requested_at', item['recorded_at']))
            if item['metadata'].get('analysis', {}).get('elapsed_seconds') is not None:
                elapsed = item['metadata']['analysis']['elapsed_seconds']
            result.append({"index": index, "filename": item["filename"] or item['title'], "status": item["job_status"],
                           "can_retry": can_retry_source(item),
                           "elapsed_seconds": round(elapsed, 1),
                           "error": item["job_error"], "coverage": item["coverage"],
                           "analysis": item["metadata"].get("analysis", {})})
        if any(item["status"] in {"pending", "running"} for item in result):
            ingestion.start_pending(store, config)
        return result

    def _recall(self, store: KnowledgeStore, config: Any, query: str, request_id: str) -> str:
        day = query_day(query)
        is_review = any(word in query for word in ("日记", "回顾", "做了什么", "做了啥", "干了什么", "经历", "总结今天"))
        if is_review and not day:
            day = datetime.now(LOCAL_TIME).date().isoformat()
        excluded = {f"desktop:user:{request_id}", f"desktop:assistant:{request_id}"}
        excluded_ids = {item["id"] for eid in excluded if (item := store.by_external_id(SCOPE, eid))}
        evidence = []
        if is_review or day:
            # Bounded excerpts in chronological order, with explicit scope/coverage.
            rows = store.sources(SCOPE, day, limit=60)
            for row in reversed(rows):
                if row["id"] in excluded_ids:
                    continue
                item = store.get(SCOPE, row["id"])
                evidence.append(self._evidence(item, bounded(item["text"], 200), "text"))
            overview = f"按 {day} 记录时间的回顾，最多最近60条来源；用户陈述不等于已验证行动。"
            if not evidence:
                overview += " 该日期没有已保存的记录，不能编造经历。"
            evidence.insert(0, {"overview": overview})
        hits = retrieve(store, SCOPE, query[:1000], day, limit=12, config=config)
        for hit in hits:
            if hit["id"] not in excluded_ids:
                evidence.append(self._evidence(hit, hit["content"], hit["anchor"]))
                if len(evidence) >= (65 if is_review or day else 6):
                    break
        # A message may describe a picture in words absent from its OCR/filename.
        # Follow the message → attachment relationship before falling back to recency.
        recalled_ids = {item.get("id") for item in evidence}
        related = []
        for source_id in {item["id"] for item in evidence if item.get("kind") == "message"}:
            message = store.get(SCOPE, source_id)
            event_id = message["metadata"].get("request_id")
            if event_id:
                for index in range(min(MAX_ATTACHMENTS, message["metadata"].get("attachment_count", 0))):
                    item = store.by_external_id(SCOPE, f"desktop:attachment:{event_id}:{index}")
                    if item and item["id"] not in recalled_ids:
                        related.append(item)
        candidates = related
        if not candidates and not any(item.get("kind") == "material" for item in evidence) and any(
                word in query for word in ("上次", "之前", "刚才", "那份", "附件")):
            recent = []
            for row in store.sources(SCOPE, limit=60):
                if row["kind"] == "material" and row["id"] not in recalled_ids and (not day or row["day"] == day):
                    item = store.get(SCOPE, row["id"])
                    recent.append(item)
                    if len(recent) >= 3:
                        break
            candidates = recent
        evidence.extend(self._evidence(item, bounded(item["text"], 1600), "text") for item in candidates[:3])
        from atri_bot.knowledge.digest import KnowledgeDigest
        domain, cards = KnowledgeDigest(store).recall(SCOPE, query, day=day, review=is_review,
                                                     source_ids=[e["id"] for e in evidence if e.get("id")], exclude=excluded_ids)
        curated = "已整理的知识目录（派生摘要与对应原文是同一处证据，不可重复计为佐证；优先据此回答重点）：\n" + json.dumps(cards, ensure_ascii=False) if cards else ""
        if domain:
            from atri_bot.knowledge.catalog import KnowledgeCatalog
            name = next((d['name'] for d in KnowledgeCatalog(store).overview(SCOPE)['domains'] if d['id'] == domain), domain)
            return f"仅检索 {name} 知识库。\n" + (curated or "尚无整理好的匹配记录，不能编造或混入其他领域。")
        return curated + ("\n历史记录证据：\n" + bounded(json.dumps(evidence, ensure_ascii=False), 18000) if evidence else "")

    @staticmethod
    def _evidence(item: dict, content: str, anchor: str) -> dict:
        return {"id": item["id"], "revision": item["revision"], "day": item["day"],
                "kind": item["kind"], "title": item["title"], "anchor": anchor,
                "coverage": item["coverage"], "parse_status": item.get("job_status"), "excerpt": content,
                "analysis": item.get("metadata", {}).get("analysis", {})}
