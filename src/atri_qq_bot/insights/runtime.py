"""OneBot 与 WebUI 共享的 insights 门面。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from ..runtime.paths import ENV_PATH
from .config import InsightsConfig
from .evaluation import EvaluationSample, EvaluationService
from .llm import StructuredLLMClient
from .store import InsightsStore
from .summary import GroupSummaryService


LOGGER = logging.getLogger("atri.insights")


class InsightsRuntime:
    def __init__(self, config: InsightsConfig | None = None) -> None:
        self.config = config or InsightsConfig.from_env()
        self.store = InsightsStore(self.config.database_path)
        self.evaluations = EvaluationService(self.store, self.config)
        self.summaries = GroupSummaryService(self.store, self.config)
        self._archive_tasks: set[asyncio.Task[Any]] = set()
        self._delivery_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        await self.evaluations.start()
        await self.summaries.start()
        LOGGER.info(
            "评测与总结旁路已启动：evaluation=%s summary=%s db=%s",
            self.config.evaluation_enabled,
            self.config.summary_enabled,
            self.config.database_path,
        )

    async def reload_config(self) -> dict[str, Any]:
        load_dotenv(ENV_PATH, override=True)
        config = InsightsConfig.from_env()
        if config.database_path != self.config.database_path:
            raise ValueError("运行中不能切换 INSIGHTS_DB_PATH，请重启 ATRI")
        self.config = config
        self.evaluations.config = config
        self.summaries.config = config
        return self.public_status()

    def archive_group_message(self, event: dict[str, Any], content: str) -> None:
        """异步归档原始群消息；失败只记日志，不影响回复策略。"""
        if not self.config.group_archive_enabled or event.get("message_type") != "group":
            return
        group_id = str(event.get("group_id") or "")
        user_id = str(event.get("user_id") or "")
        message_id = str(event.get("message_id") or "")
        timestamp = event.get("time")
        try:
            created_at = datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError, OSError):
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not message_id:
            digest = hashlib.sha1(
                f"{group_id}|{user_id}|{created_at}|{content}".encode("utf-8", errors="replace")
            ).hexdigest()
            message_id = digest
        sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
        nickname = str(sender.get("card") or sender.get("nickname") or user_id)
        # 保留 OneBot 图片/表情的可访问 URL。旧版只把图片压成文件名，报告无法展示原图；
        # URL 不存在时仍保存 file_id，渲染层会显示“图片”占位而不会泄漏编码。
        media: list[dict[str, str]] = []
        raw_segments = event.get("message")
        if isinstance(raw_segments, list):
            for segment in raw_segments:
                if not isinstance(segment, dict) or str(segment.get("type") or "") not in {"image", "mface", "face"}:
                    continue
                data = segment.get("data") if isinstance(segment.get("data"), dict) else segment
                url = str(data.get("url") or data.get("proxy_url") or "").strip()
                file_id = str(data.get("file") or data.get("file_id") or "").strip()
                if url or file_id:
                    media.append({"type": str(segment.get("type") or "image"), "url": url, "file": file_id})
        group_name = str(event.get("group_name") or "").strip()
        if group_name:
            # OneBot/NapCat 部分版本会把群名直接放在事件里；有则缓存，旧事件仍可正常归档。
            name_task = asyncio.create_task(
                asyncio.to_thread(self.store.set_group_name, group_id, group_name)
            )
            self._archive_tasks.add(name_task)
            name_task.add_done_callback(self._archive_tasks.discard)
            name_task.add_done_callback(self._log_archive_error)
        task = asyncio.create_task(
            asyncio.to_thread(
                self.store.add_group_message,
                message_key=f"{group_id}:{message_id}",
                group_id=group_id,
                user_id=user_id,
                nickname=nickname,
                content=str(content),
                message_type="text",
                created_at=created_at,
                media=media,
            )
        )
        self._archive_tasks.add(task)
        task.add_done_callback(self._archive_tasks.discard)
        task.add_done_callback(self._log_archive_error)

    def submit_evaluation(self, sample: EvaluationSample) -> None:
        self.evaluations.submit(sample)

    def submit_evaluation_failure(self, sample: EvaluationSample, error: str) -> None:
        self.evaluations.submit_failure(sample, error)

    def record_delivery(self, **payload: Any) -> None:
        """异步记录消息发送结果，不阻塞 OneBot 发送链路。"""
        task = asyncio.create_task(asyncio.to_thread(self.store.record_delivery, **payload))
        self._delivery_tasks.add(task)
        task.add_done_callback(self._delivery_tasks.discard)
        task.add_done_callback(self._log_archive_error)

    def public_status(self) -> dict[str, Any]:
        return {
            "config": self.config.public_dict(),
            "evaluation": self.evaluations.status(),
            "summary": {
                "enabled": self.config.summary_enabled,
                "archive_enabled": self.config.group_archive_enabled,
                "schedule_enabled": self.config.summary_schedule_enabled,
                "schedule_time": self.config.summary_schedule_time,
                "schedule_period": self.config.summary_schedule_period,
            },
        }

    async def check_judge_connection(self) -> None:
        """主动检查评测供应商，避免仅凭“已填写密钥”误报可用。"""
        client = StructuredLLMClient(
            base_url=self.config.judge_base_url,
            api_key=self.config.judge_api_key,
            model=self.config.judge_model,
            timeout=self.config.judge_timeout_seconds,
        )
        await client.check_connection()

    async def close(self) -> None:
        if self._archive_tasks:
            await asyncio.gather(*tuple(self._archive_tasks), return_exceptions=True)
        if self._delivery_tasks:
            await asyncio.gather(*tuple(self._delivery_tasks), return_exceptions=True)
        await self.evaluations.close()
        await self.summaries.close()

    @staticmethod
    def _log_archive_error(task: asyncio.Task[Any]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            error = task.exception()
            if error:
                LOGGER.warning("群消息旁路归档失败：%s", error)
