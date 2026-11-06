"""Conservative source spans shared by rule and model extraction.

These checks establish source attribution, not semantic truth. Unrecognised
statements remain conversational context; model interpretations remain candidates.
"""
from __future__ import annotations

import re


_QUOTED = re.compile(r'```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$)|“[^”]*(?:”|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|"[^"\n]*(?:"|$)')
_NON_ASSERTION = re.compile(r'如果|假如|假设|要是|假装|扮演|比如|例如|转述|原话|台词|是不是|会不会|能不能|(?:朋友|同学|同事|他|她)(?:说|表示|提到)[：:，,]')


def assertion_spans(text: str) -> list[tuple[str, int, int]]:
    """Return unquoted assertion clauses with offsets in the original message.

    Reject hypothetical sentences as a whole, so their comma-separated
    consequences cannot accidentally turn into self reports.
    """
    # QQ 引用包可在摘要中被压成一行；不能只靠引号/换行辨认说话人。
    # 保留原文坐标，让同步规则与后台模型证据校验使用同一边界。
    start_at = 0
    if text.lstrip().startswith('【引用消息】'):
        boundary = text.find('【用户当前消息】')
        if boundary < 0:
            return []
        start_at = boundary + len('【用户当前消息】')
    quoted = [(m.start(), m.end()) for m in _QUOTED.finditer(text)]
    result = []
    for sentence in re.compile(r'[^。！？!?\n]+[。！？!?]?').finditer(text, start_at):
        body = sentence.group()
        if _NON_ASSERTION.search(body) or body.endswith(('?', '？')):
            continue
        for clause in re.finditer(r'[^，,；;。！？!?]+', body):
            raw = clause.group()
            value = raw.strip()
            start = sentence.start() + clause.start() + len(raw) - len(raw.lstrip())
            end = start + len(value)
            if (not value or value.endswith(('吗', '么'))
                    or any(start < right and end > left for left, right in quoted)):
                continue
            result.append((value, start, end))
    return result


def evidence_span(text: str, evidence: str, scope_kind: str) -> tuple[int, int] | None:
    """Require a verbatim span of a current attributable assertion, never a summary."""
    for clause, start, _ in assertion_spans(text):
        # Personal interpretation cannot be silently promoted to group culture.
        prefix = r'^(?:本群|我们群|群里|大家|我们)' if scope_kind == 'group' else r'^(?:我(?!们)|其实我|现在我|目前我|最近|这段时间|今天|明天|后天|今晚|以后|请|不要|别)'
        if not re.search(prefix, clause):
            continue
        offset = clause.find(evidence)
        if evidence and offset >= 0:
            return start + offset, start + offset + len(evidence)
    return None
