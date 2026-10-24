"""Durable import jobs. Leases prevent duplicate workers from committing stale results."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from .store import KnowledgeStore

LOG = logging.getLogger(__name__)
_workers: set[str] = set()
_rerun: set[str] = set()
_lock = threading.Lock()


def archive_analysis(store: KnowledgeStore, scope: str, result: Any, *, event_id: str = "",
                     occurred_at: float | None = None) -> list[str]:
    """Fresh tool results only. Summaries are labelled; they never pretend to be full text."""
    materials = getattr(result, "knowledge_materials", [])
    if not materials:
        materials = [{"title": "媒体分析记录", "locator": ", ".join(getattr(result, "sources", [])),
                      "text": "\n".join(getattr(result, "findings", [])),
                      "coverage": "analysis_summary:" + str(getattr(result, "read_level", "metadata_only")),
                      "raw": getattr(result, "visual_data", None),
                      "filename": "visual.bin"}]
    ids = []
    for i, material in enumerate(materials):
        item = store.create(scope, material.get("text", ""), title=material.get("title", "资料"), kind="material",
                            occurred_at=occurred_at, locator=material.get("locator", ""),
                            filename=material.get("filename", ""), raw=material.get("raw"),
                            blocks=material.get("blocks"), coverage=material.get("coverage", "partial_content"),
                            metadata={"limitations": list(getattr(result, "limitations", []))},
                            external_id=f"material:{event_id}:{i}" if event_id else None)
        ids.append(item["id"])
    return ids


def run_pending(store: KnowledgeStore, config: Any, *, max_jobs: int = 8, source_id: str = "") -> int:
    from ..toolbox import ToolAnalyzer

    analyzer = ToolAnalyzer(config)
    count = 0
    for _ in range(max_jobs):
        job = store.claim_job(source_id=source_id)
        if job is None:
            break
        try:
            async def analyze():
                if job['metadata'].get('import_url'):
                    message_id = job['metadata'].get('message_source_id')
                    message = store.get(job['scope'], message_id) if message_id else None
                    operation = analyzer.analyze_url_material(job['locator'], message['text'] if message else '')
                else:
                    operation = analyzer._analyze_file_bytes(job['raw'] or b'', job['locator'], job['filename'])
                return await asyncio.wait_for(operation, timeout=max(90, float(getattr(config, 'toolbox_video_deadline_seconds', 60)) + 30))
            result = asyncio.run(analyze())
            materials = getattr(result, 'knowledge_materials', [])
            if result.read_level == "metadata_only":
                # QQ can continue with share-title evidence when a remote page
                # is unavailable. Preserve that evidence with honest coverage;
                # a bare URL or a received-file notice still cannot succeed.
                materials = [m for m in materials if m.get('coverage') == 'user_share_metadata_only'
                             and m.get('text', '').strip()]
                if not materials:
                    raise ValueError("；".join(result.limitations) or "未提取到可检索正文，原件已保留")
            if materials:
                text = "\n\n".join(m.get("text", "") for m in materials)
                blocks = [b for m in materials for b in (m.get("blocks") or [{"anchor": "text", "text": m.get("text", "")}])]
                coverage = "; ".join(dict.fromkeys(m.get("coverage", "partial_content") for m in materials))
            else:
                text = "\n".join(result.findings)
                blocks = None
                coverage = "analysis_summary:" + result.read_level
            if not text.strip():
                raise ValueError("；".join(result.limitations) or "未提取到可检索正文，原件已保留")
            store.finish_job(job, text=text, blocks=blocks, coverage=coverage, analysis={
                "read_level": result.read_level,
                "visual_status": getattr(result, "visual_status", ""),
                "limitations": [str(item)[:300] for item in result.limitations[:8]],
                "elapsed_seconds": round(max(0, time.time()-job['recorded_at']), 1),
            })
        except Exception as exc:
            store.finish_job(job, error=str(exc))
            LOG.warning("knowledge import failed: %s", exc)
        count += 1
    return count


def start_pending(store: KnowledgeStore, config: Any) -> None:
    """Called on import and workbench reads; persisted pending/expired jobs resume there."""
    from . import digest
    digest.start_pending(store, config, "desktop:owner")
    key = str(store.path.resolve())
    with _lock:
        if key in _workers:
            _rerun.add(key)
            return
        _workers.add(key)

    def work() -> None:
        released = False
        try:
            while True:
                while run_pending(store, config) == 8:
                    pass
                with _lock:
                    if key in _rerun:
                        _rerun.discard(key)
                        continue
                    _workers.discard(key)
                    released = True
                    break
        except Exception:
            LOG.exception("knowledge worker stopped; jobs remain resumable")
        finally:
            digest.start_pending(store, config, "desktop:owner")
            if not released:
                with _lock:
                    _workers.discard(key)
                    _rerun.discard(key)

    threading.Thread(target=work, name="atri-knowledge-import", daemon=True).start()
