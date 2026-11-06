"""Complete, independently editable card covers. Never truncate scientific text."""
from __future__ import annotations


def cover_for(data: dict, *, revision=1, locked=False) -> dict:
    supplied = data.get('cover')
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError('封面必须为结构化内容')
        result = {}
        for key, limit in [('title', 200), ('core', 20000), ('context', 12000), ('result', 12000)]:
            text = supplied.get(key, '')
            if not isinstance(text, str) or len(text) > limit:
                raise ValueError(f'封面 {key} 最多 {limit} 字')
            result[key] = text.strip()
        points = supplied.get('key_points', [])
        if not isinstance(points, list) or len(points) > 30 or any(not isinstance(p, str) or len(p) > 2000 for p in points):
            raise ValueError('封面要点最多30条，每条2000字')
        result['key_points'] = list(dict.fromkeys(p.strip() for p in points if p.strip()))
        result['title'] = result['title'] or data.get('title', '')
        result['core'] = result['core'] or data.get('summary', '')
        if data.get('format') == 'problem' and not result['result']:
            result['result'] = data.get('answer') or '来源尚未提供答案'
    else:
        problem = data.get('format') == 'problem'
        result = {'title': data.get('title', ''),
                  'core': (data.get('question') if problem else '') or data.get('summary', ''),
                  'context': '', 'result': (data.get('answer') or '来源尚未提供答案') if problem else '',
                  'key_points': list(dict.fromkeys(p for p in data.get('points', [])
                                                  if p and p != data.get('summary')))}
    return result | {'revision': revision, 'locked': bool(locked)}
