from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus


DEFAULT_SEARCH_TIMEOUT_SECONDS = 6.0
DEFAULT_SEARCH_MAX_RESULTS = 5


async def search_web(arguments: dict[str, Any] | None = None, config: Any | None = None) -> str:
    args = arguments or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return "搜索失败：缺少搜索关键词。"

    max_results = _positive_int(
        args.get("max_results"),
        int(getattr(config, "web_search_max_results", DEFAULT_SEARCH_MAX_RESULTS) or DEFAULT_SEARCH_MAX_RESULTS),
    )
    max_results = max(1, min(8, max_results))
    timeout = float(
        getattr(config, "web_search_timeout_seconds", DEFAULT_SEARCH_TIMEOUT_SECONDS)
        or DEFAULT_SEARCH_TIMEOUT_SECONDS
    )

    try:
        import httpx

        url = _bing_news_rss_url(query)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
        return format_search_results(query, parse_bing_news_rss(response.text, max_results))
    except Exception as exc:
        return f"搜索失败：{_short_error(exc)}。不要编造实时信息，可以说明现在没有拿到可靠搜索结果。"


def _bing_news_rss_url(query: str) -> str:
    return f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"


def parse_bing_news_rss(text: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    results: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        published_at = _clean_text(item.findtext("pubDate") or "")
        summary = _clean_text(item.findtext("description") or "")
        if not title and not summary:
            continue
        results.append(
            {
                "title": title,
                "url": link,
                "published_at": published_at,
                "summary": summary,
            }
        )
        if len(results) >= max(1, max_results):
            break
    return results


def format_search_results(query: str, results: list[dict[str, str]]) -> str:
    searched_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    if not results:
        return (
            f"搜索时间：{searched_at} Asia/Shanghai\n"
            f"搜索关键词：{query}\n"
            "没有搜索到明确结果。不要编造实时信息，可以说明没拿到可靠来源。"
        )

    lines = [
        f"搜索时间：{searched_at} Asia/Shanghai",
        f"搜索关键词：{query}",
        "搜索结果如下。回答时要结合发布时间判断时效性，无法确认发布时间时不要声称一定最新：",
    ]
    for index, result in enumerate(results, start=1):
        title = result.get("title") or "无标题"
        published_at = result.get("published_at") or "未标明"
        summary = _shorten(result.get("summary") or "无摘要", 220)
        url = result.get("url") or "无链接"
        lines.append(
            f"{index}. 标题：{title}\n"
            f"   发布时间：{published_at}\n"
            f"   摘要：{summary}\n"
            f"   URL：{url}"
        )
    return "\n".join(lines)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(1, default)
    return max(1, parsed)


def _clean_text(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _shorten(value: str, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"\s+", " ", text)
    return _shorten(text, 160)
