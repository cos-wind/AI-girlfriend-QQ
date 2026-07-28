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

    errors: list[str] = []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for source_name, url in (
                ("Google News", _google_news_rss_url(query)),
                ("Bing News", _bing_news_rss_url(query)),
            ):
                try:
                    response = await client.get(url, headers=_request_headers())
                    response.raise_for_status()
                    results = parse_news_rss(response.text, max_results)
                    if results:
                        return format_search_results(query, results, source_name=source_name)
                    errors.append(f"{source_name}: 没有结果")
                except Exception as exc:
                    errors.append(f"{source_name}: {_short_error(exc)}")
    except Exception as exc:
        errors.append(_short_error(exc))
    detail = "；".join(errors)[:300] or "未知错误"
    return f"搜索失败：{detail}。不要编造实时信息，可以说明现在没有拿到可靠搜索结果。"


def _google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def _bing_news_rss_url(query: str) -> str:
    return f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"


def parse_bing_news_rss(text: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
    return parse_news_rss(text, max_results)


def parse_news_rss(text: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
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


def format_search_results(
    query: str,
    results: list[dict[str, str]],
    source_name: str = "新闻 RSS",
) -> str:
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
        f"聚合来源：{source_name}",
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


def _request_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        )
    }
