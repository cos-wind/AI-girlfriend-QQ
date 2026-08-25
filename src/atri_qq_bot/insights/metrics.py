"""可插拔评测维度和统一 Judge 提示词。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    rubric: str
    requires_context: bool = False


# 每个维度是一条独立注册项；新增维度只需补一个 MetricSpec，不需要改数据库。
METRIC_REGISTRY: dict[str, MetricSpec] = {
    "relevancy": MetricSpec("relevancy", "相关性", "回答是否直接回应问题，避免跑题和无关内容。"),
    "accuracy": MetricSpec("accuracy", "准确性", "事实、数字、因果和概念是否正确；无法核实时降低置信度并明确说明。"),
    "completeness": MetricSpec("completeness", "完整性", "是否覆盖问题中所有明确要求和关键子问题。"),
    "coherence": MetricSpec("coherence", "连贯性", "逻辑顺序、前后一致性、表达结构是否清楚自然。"),
    "faithfulness": MetricSpec(
        "faithfulness",
        "忠实度",
        "先拆分回答中的可验证声明，再判断每条声明能否由检索上下文推出；按受支持声明比例评分。",
        requires_context=True,
    ),
    "hallucination": MetricSpec(
        "hallucination",
        "无幻觉程度",
        "检查无依据的实体、数字、出处、能力或事件。5 分表示没有发现编造，0 分表示存在严重编造。",
    ),
}


def enabled_metrics(names: Iterable[str]) -> tuple[MetricSpec, ...]:
    return tuple(METRIC_REGISTRY[name] for name in names if name in METRIC_REGISTRY)


def build_judge_prompt(
    *,
    question: str,
    answer: str,
    context: str,
    metrics: tuple[MetricSpec, ...],
) -> tuple[str, str]:
    schema_lines = ",\n".join(
        f'    "{metric.name}": {{"score": 0到5的数字或null, "reason": "中文理由", "issues": ["具体问题"]}}'
        for metric in metrics
    )
    rubric_lines = "\n".join(
        f"- {metric.name}（{metric.label}）：{metric.rubric}" for metric in metrics
    )
    context_text = context.strip() or "[本轮没有可用的检索上下文]"
    system = (
        "你是严格、可复现的中文 AI 回复质量评审。不要迎合被评回答。"
        "分数范围 0~5，5 最好；证据不足时必须在 reason 说明，不得虚构事实。"
        "faithfulness 没有检索上下文时返回 null；hallucination 的高分代表更少幻觉。"
        "输出必须是合法 JSON 对象。"
    )
    prompt = f"""请按以下维度独立评分：
{rubric_lines}

评分锚点：5=优秀且无明显缺陷，4=良好有轻微缺陷，3=基本可用，2=明显不足，1=严重不足，0=完全失败。

<user_question>
{question[:12000]}
</user_question>
<assistant_answer>
{answer[:16000]}
</assistant_answer>
<retrieved_context>
{context_text[:24000]}
</retrieved_context>

只输出如下 JSON 结构：
{{
  "dimensions": {{
{schema_lines}
  }},
  "issues": ["跨维度的主要问题，最多5条"]
}}
"""
    return system, prompt


def normalize_judge_result(
    payload: dict[str, Any], metrics: tuple[MetricSpec, ...]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    raw_dimensions = payload.get("dimensions")
    raw_dimensions = raw_dimensions if isinstance(raw_dimensions, dict) else {}
    result: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for metric in metrics:
        raw = raw_dimensions.get(metric.name)
        raw = raw if isinstance(raw, dict) else {}
        value = raw.get("score")
        try:
            score = max(0.0, min(5.0, float(value))) if value is not None else None
        except (TypeError, ValueError):
            score = None
        metric_issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
        clean_metric_issues = [str(item).strip()[:240] for item in metric_issues if str(item).strip()]
        issues.extend(clean_metric_issues)
        result[metric.name] = {
            "score": score,
            "reason": str(raw.get("reason") or "模型未提供理由")[:2000],
            "metadata": {"issues": clean_metric_issues},
        }
    top_issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    issues.extend(str(item).strip()[:240] for item in top_issues if str(item).strip())
    return result, list(dict.fromkeys(issues))[:12]

