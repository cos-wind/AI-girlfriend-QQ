"""Read public share data without executing page scripts or inventing media content."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import unquote, urlparse


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').lower()
    return any(host == root or host.endswith('.' + root) for root in ('douyin.com', 'iesdouyin.com'))


def share_target(url: str) -> tuple[str, str] | None:
    if not is_douyin_url(url):
        return None
    match = re.search(r'/(?:share/)?(video|note)/(\d+)(?:/|$)', urlparse(url).path)
    return (match[1], match[2]) if match else None


def public_item(text: str, item_id: str) -> dict:
    """Only accept the requested work, never recommended videos or layout metadata."""
    payloads = []
    for pattern in (r'window\._ROUTER_DATA\s*=\s*', r'window\.__INITIAL_STATE__\s*=\s*'):
        match = re.search(pattern, text)
        if match:
            try:
                payloads.append(json.JSONDecoder().raw_decode(text[match.end():].lstrip())[0])
            except ValueError:
                pass
    render = re.search(r'<script\b[^>]*\bid=["\x27]RENDER_DATA["\x27][^>]*>(.*?)</script>', text, re.S)
    if render:
        try:
            payloads.append(json.loads(unquote(html.unescape(render[1]))))
        except ValueError:
            pass
    stack = list(payloads)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if str(value.get('aweme_id') or value.get('awemeId') or '') == item_id:
                if isinstance(value.get('desc'), str) and value['desc'].strip():
                    return value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return {}
