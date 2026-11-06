"""Conservative event extraction; no database, model calls or score authority.

Candidates retain exact source spans. These rules deliberately cover only clear
addressed warmth and shared accomplishments, not general semantic understanding.
"""
from __future__ import annotations

import re

from .appraisal import appraise, QUOTE_MARK, UNCERTAIN_CONTEXT


def candidates(text: str) -> list[dict]:
    # Reject the whole quoted/hypothetical context before splitting clauses.
    if len(text) > 1000 or QUOTE_MARK.search(text) or UNCERTAIN_CONTEXT.search(text):
        return []
    result = {}
    for match in re.finditer(r'[^，,。！!；;\n]+', text):
        clause = match.group().strip()
        if re.search(r'他说|她说|它说|你说|别人说|曾经|昨天|上次|去年|以前|记得|如果|要是|打算|准备|希望|将来|以后', clause):
            continue
        event = appraise(clause)
        if event.kind not in {'understanding', 'warmth', 'shared'}:
            continue
        kind = event.kind
        topic = ''
        base, strength = (.8, 1) if kind == 'understanding' else (.2, 1)
        if kind == 'shared':
            completion = re.search(r'(?:做完|完成|学会)(?:了)?\s*(.+)', clause)
            if not completion or re.search(r'没|未|不|还没', clause):
                continue
            topic = re.sub(r'[\W_]+', '', completion[1]).casefold()
            if not topic:
                continue
            base, strength = 1, .5  # User report, not an independently verified receipt.
        key = kind + ':' + topic
        result.setdefault(key, {'kind': kind, 'topic': topic, 'occurrence': key,
                               'evidence': match.group(), 'start': match.start(), 'end': match.end(),
                               'base': base, 'evidence_strength': strength,
                               'relevance': 1, 'incremental_progress': 1})
    return list(result.values())
