"""不阻塞主回复流程的评测队列。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from dataclasses import dataclass
from typing import Any

from .config import InsightsConfig
from .embeddings import SemanticEncoder
from .llm import StructuredLLMClient
from .metrics import build_judge_prompt, enabled_metrics, normalize_judge_result
from .store import InsightsStore


LOGGER = logging.getLogger("atri.insights.evaluation")

# 事实性风险比表达风格更应该影响总体质量。权重只影响汇总分，不改变各维度原始分。
OVERALL_WEIGHTS: dict[str, float] = {
    "relevancy": 1.0,
    "accuracy": 1.35,
    "completeness": 1.0,
    "coherence": 0.8,
    "faithfulness": 1.3,
    "hallucination": 1.25,
}


def calculate_overall_score(scores: dict[str, dict[str, Any]]) -> float | None:
    """使用加权几何均值汇总分数，避免高分维度掩盖关键风险维度。

    算术平均会让一个 1 分的准确性被多个 5 分维度“冲淡”。几何均值对低分
    更敏感，同时仍保持 0~5 范围；缺失维度不参与计算，兼容可插拔评测。
    """
    weighted_log = 0.0
    total_weight = 0.0
    for name, item in scores.items():
        if not isinstance(item, dict) or item.get("score") is None:
            continue
        try:
            value = max(0.0, min(5.0, float(item["score"])))
        except (TypeError, ValueError):
            continue
        weight = float(OVERALL_WEIGHTS.get(name, 1.0))
        total_weight += weight
        # 0 分仍保留为极小正数，避免 log(0)；最终再映射回 0~5。
        weighted_log += weight * math.log(max(value / 5.0, 1e-6))
    if total_weight <= 0:
        return None
    return round(5.0 * math.exp(weighted_log / total_weight), 4)


@dataclass(frozen=True)
class EvaluationSample:
    turn_id: str
    conversation_id: str
    group_id: str
    question: str
    answer: str
    context: str = ""
    # system=ATRi 实际回复自动采集；model=WebUI 手动提交的模型评测样本。
    source: str = "system"
    # 评测所使用的能力分类：chat / vision / voice。
    model_type: str = "chat"
    model_name: str = ""


def context_from_tool_context(tool_context: Any | None) -> str:
    """把现有工具/RAG 对象投影成稳定文本，不让评测模块依赖其具体类型。"""
    if tool_context is None:
        return ""
    prompt_context = getattr(tool_context, "prompt_context", None)
    if callable(prompt_context):
        with contextlib.suppress(Exception):
            value = str(prompt_context() or "").strip()
            if value:
                return value[:24000]
    material = getattr(tool_context, "material_context", None)
    if material is not None and material is not tool_context:
        nested = context_from_tool_context(material)
        if nested:
            return nested
    parts: list[str] = []
    for name in ("findings", "limitations"):
        values = getattr(tool_context, name, None)
        if isinstance(values, (list, tuple)):
            parts.extend(str(value) for value in values if str(value).strip())
    return "\n".join(parts)[:24000]


class EvaluationService:
    def __init__(self, store: InsightsStore, config: InsightsConfig) -> None:
        self.store = store
        self.config = config
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=config.evaluation_queue_size)
        self._workers: list[asyncio.Task[None]] = []
        self._persistence_tasks: set[asyncio.Task[Any]] = set()
        self._encoder = SemanticEncoder(
            config.embedding_model, local_only=config.embedding_local_only
        )
        self._semantic_warning_emitted = False

    async def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"atri-evaluation-{index}")
            for index in range(self.config.evaluation_workers)
        ]
        # 先启动消费者再恢复持久化队列，避免待恢复记录超过 queue_size 时启动死锁。
        for evaluation_id in await asyncio.to_thread(self.store.queued_evaluation_ids):
            await self._queue.put(evaluation_id)

    def submit(self, sample: EvaluationSample) -> None:
        """只调度持久化任务并立即返回；调用方不会等待 SQLite 或模型。"""
        if not self._can_submit(sample) or not sample.question.strip() or not sample.answer.strip():
            return
        task = asyncio.create_task(self._persist_and_enqueue(sample))
        self._persistence_tasks.add(task)
        task.add_done_callback(self._persistence_tasks.discard)
        task.add_done_callback(self._log_task_error)

    def submit_failure(self, sample: EvaluationSample, error: str) -> None:
        """旁路记录一次未发送回复；不进入 Judge 队列，也不阻塞聊天。"""
        if not self._can_submit(sample) or not sample.question.strip():
            return
        task = asyncio.create_task(self._persist_failure(sample, error))
        self._persistence_tasks.add(task)
        task.add_done_callback(self._persistence_tasks.discard)
        task.add_done_callback(self._log_task_error)

    async def enqueue(self, sample: EvaluationSample) -> str:
        """为 WebUI 手动评测同步返回记录 ID；模型评测不阻塞机器人主流程。"""
        if not self._can_submit(sample):
            raise RuntimeError("当前评测模式未启用")
        if not sample.question.strip() or not sample.answer.strip():
            raise ValueError("问题和回答不能为空")
        evaluation_id = await asyncio.to_thread(
            self.store.create_evaluation,
            turn_id=sample.turn_id,
            conversation_id=sample.conversation_id,
            group_id=sample.group_id,
            question=sample.question,
            answer=sample.answer,
            context=sample.context,
            judge_model=self.config.judge_model,
            source=sample.source,
            model_type=sample.model_type,
            model_name=sample.model_name,
        )
        await self._queue.put(evaluation_id)
        return evaluation_id

    def _can_submit(self, sample: EvaluationSample) -> bool:
        if not self.config.evaluation_enabled:
            return False
        if sample.source == "model":
            return self.config.model_evaluation_enabled
        return self.config.system_evaluation_enabled

    async def _persist_and_enqueue(self, sample: EvaluationSample) -> None:
        evaluation_id = await asyncio.to_thread(
            self.store.create_evaluation,
            turn_id=sample.turn_id,
            conversation_id=sample.conversation_id,
            group_id=sample.group_id,
            question=sample.question,
            answer=sample.answer,
            context=sample.context,
            source=sample.source,
            model_type=sample.model_type,
            model_name=sample.model_name,
            judge_model=self.config.judge_model,
        )
        await self._queue.put(evaluation_id)

    async def _persist_failure(self, sample: EvaluationSample, error: str) -> None:
        evaluation_id = await asyncio.to_thread(
            self.store.create_evaluation,
            turn_id=sample.turn_id,
            conversation_id=sample.conversation_id,
            group_id=sample.group_id,
            question=sample.question,
            answer=sample.answer,
            context=sample.context,
            source=sample.source,
            model_type=sample.model_type,
            model_name=sample.model_name,
            judge_model=self.config.judge_model,
        )
        await asyncio.to_thread(
            self.store.fail_evaluation,
            evaluation_id,
            str(error or "回复失败")[:2000],
        )

    async def retry(self, evaluation_id: str) -> bool:
        changed = await asyncio.to_thread(self.store.retry_evaluation, evaluation_id)
        if changed:
            await self._queue.put(evaluation_id)
        return changed

    async def retry_failed(self, source: str = "") -> int:
        """批量重试失败记录；通常在修正 Judge Key 后使用。"""
        ids = await asyncio.to_thread(self.store.failed_evaluation_ids, source)
        count = 0
        for evaluation_id in ids:
            if await asyncio.to_thread(self.store.retry_evaluation, evaluation_id):
                await self._queue.put(evaluation_id)
                count += 1
        return count

    async def _worker(self, index: int) -> None:
        while True:
            evaluation_id = await self._queue.get()
            try:
                await self._evaluate(evaluation_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("回复评测失败：id=%s error=%s", evaluation_id, exc)
                await asyncio.to_thread(self.store.fail_evaluation, evaluation_id, str(exc))
            finally:
                self._queue.task_done()

    async def _evaluate(self, evaluation_id: str) -> None:
        record = await asyncio.to_thread(self.store.evaluation_input, evaluation_id)
        if not record:
            return
        await asyncio.to_thread(self.store.mark_evaluation_running, evaluation_id)
        metrics = enabled_metrics(self.config.dimensions)
        if not metrics:
            raise RuntimeError("没有启用任何评测维度")
        client = StructuredLLMClient(
            base_url=self.config.judge_base_url,
            api_key=self.config.judge_api_key,
            model=self.config.judge_model,
            timeout=self.config.judge_timeout_seconds,
        )
        system, prompt = build_judge_prompt(
            question=str(record["question"]),
            answer=str(record["answer"]),
            context=str(record["context"]),
            metrics=metrics,
        )
        judge_payload = await client.complete_json(system=system, prompt=prompt)
        scores, issues = normalize_judge_result(judge_payload, metrics)

        semantic: float | None = None
        if self.config.semantic_enabled:
            try:
                semantic = await asyncio.to_thread(
                    self._encoder.similarity,
                    str(record["question"]),
                    str(record["answer"]),
                )
            except Exception as exc:
                if not self._semantic_warning_emitted:
                    LOGGER.warning("语义相似度辅助暂不可用：%s", exc)
                    self._semantic_warning_emitted = True

        # 相似度只辅助相关性，避免一个粗粒度向量分数污染事实性等维度。
        relevancy = scores.get("relevancy")
        if relevancy and relevancy.get("score") is not None and semantic is not None:
            judge_score = float(relevancy["score"])
            semantic_score = max(0.0, min(5.0, (semantic + 1.0) * 2.5))
            weight = self.config.semantic_weight
            relevancy["score"] = round(judge_score * (1.0 - weight) + semantic_score * weight, 4)
            relevancy["metadata"].update(
                {"judge_score": judge_score, "semantic_score": semantic_score, "semantic_weight": weight}
            )

        overall = calculate_overall_score(scores)
        await asyncio.to_thread(
            self.store.complete_evaluation,
            evaluation_id,
            scores=scores,
            semantic_similarity=semantic,
            overall_score=overall,
            issues=issues,
        )
        LOGGER.info("回复评测完成：id=%s overall=%s", evaluation_id, overall)

    async def close(self) -> None:
        if self._persistence_tasks:
            await asyncio.gather(*tuple(self._persistence_tasks), return_exceptions=True)
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers.clear()

    @staticmethod
    def _log_task_error(task: asyncio.Task[Any]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            error = task.exception()
            if error is not None:
                LOGGER.warning("评测任务入队失败：%s", error)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.evaluation_enabled,
            "judge_ready": self.config.judge_ready,
            "model": self.config.judge_model,
            "dimensions": list(self.config.dimensions),
            "semantic_enabled": self.config.semantic_enabled,
            "queue_size": self._queue.qsize(),
            "workers": len(self._workers),
        }
