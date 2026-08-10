from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus, urlsplit


DEFAULT_SEARCH_TIMEOUT_SECONDS = 6.0
DEFAULT_SEARCH_MAX_RESULTS = 5


async def search_web(arguments: dict[str, Any] | None = None, config: Any | None = None) -> str:
    args = arguments or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return "搜索失败：缺少搜索关键词。"

    mode = str(args.get("mode") or "auto").strip().casefold()
    if mode not in {"auto", "web", "news", "research"}:
        mode = "auto"
    domains = _normalize_domains(args.get("domains"))
    effective_query = _domain_scoped_query(query, domains)

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
            if mode == "research":
                research_results, research_sources = await _search_research_sources(
                    client,
                    query,
                    max_results,
                    domains,
                )
                if research_results:
                    formatted = format_search_results(
                        query,
                        research_results,
                        source_name=" + ".join(research_sources),
                        mode=mode,
                        domains=domains,
                    )
                    return await _append_primary_source_excerpt(
                        formatted,
                        research_results,
                        config,
                    )
            for source_name, url in _search_sources(effective_query, mode):
                try:
                    response = await client.get(url, headers=_request_headers())
                    response.raise_for_status()
                    results = parse_news_rss(response.text, max_results)
                    if domains:
                        results = _filter_results_by_domains(results, domains)
                    if results:
                        return format_search_results(
                            query,
                            results,
                            source_name=source_name,
                            mode=mode,
                            domains=domains,
                        )
                    errors.append(f"{source_name}: 没有结果")
                except Exception as exc:
                    errors.append(f"{source_name}: {_short_error(exc)}")
    except Exception as exc:
        errors.append(_short_error(exc))
    detail = "；".join(errors)[:300] or "未知错误"
    return f"搜索失败：{detail}。不要编造实时信息，可以说明现在没有拿到可靠搜索结果。"


async def _search_research_sources(
    client: Any,
    query: str,
    max_results: int,
    domains: list[str],
) -> tuple[list[dict[str, str]], list[str]]:
    results: list[dict[str, str]] = []
    sources: list[str] = []
    compact_query = _compact_research_query(query)
    per_source_limit = max(2, (max_results + 1) // 2)
    use_arxiv = not domains or _domain_selected(domains, "arxiv.org")
    use_github = not domains or _domain_selected(domains, "github.com")

    if use_arxiv:
        try:
            response = await client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{compact_query.split()[0]}",
                    "start": 0,
                    "max_results": per_source_limit,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
                headers=_request_headers(),
            )
            response.raise_for_status()
            arxiv_results = parse_arxiv_atom(response.text, per_source_limit)
            if arxiv_results:
                results.extend(arxiv_results)
                sources.append("arXiv")
        except Exception:
            pass

    if use_github:
        try:
            response = await client.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": compact_query,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": per_source_limit,
                },
                headers={**_request_headers(), "Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            github_results = parse_github_repository_search(response.json(), per_source_limit)
            if github_results:
                results.extend(github_results)
                sources.append("GitHub")
        except Exception:
            pass

    return _deduplicate_results(results, max_results), sources


def _compact_research_query(query: str) -> str:
    tokens = re.findall(r"[\w.+-]{2,}", str(query or ""), flags=re.UNICODE)
    stopwords = {
        "latest",
        "current",
        "research",
        "limitations",
        "limitation",
        "benchmark",
        "benchmarks",
        "understanding",
        "evaluation",
        "evaluate",
        "study",
        "studies",
        "2025",
        "2026",
    }
    specific = [
        token
        for token in tokens
        if token.casefold() not in stopwords
        and (any(char.isdigit() for char in token) or "-" in token or "." in token)
    ]
    topical = [
        token
        for token in tokens
        if token.casefold() not in stopwords and token not in specific
    ]
    selected = specific[:2] + topical[: max(0, 3 - len(specific[:2]))]
    return " ".join(selected or tokens[:3] or [str(query or "").strip()])


def parse_arxiv_atom(text: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", namespace):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=namespace))
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=namespace))
        published = _clean_text(entry.findtext("atom:published", default="", namespaces=namespace))
        url = _clean_text(entry.findtext("atom:id", default="", namespaces=namespace))
        if not title or not url:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "published_at": published,
                "summary": summary,
                "source_type": "arXiv 预印本（不等于已经形成学界定论）",
            }
        )
        if len(results) >= max(1, max_results):
            break
    return results


def parse_github_repository_search(
    payload: Any,
    max_results: int = DEFAULT_SEARCH_MAX_RESULTS,
) -> list[dict[str, str]]:
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    results: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("full_name") or item.get("name") or "").strip()
        url = str(item.get("html_url") or "").strip()
        if not title or not url:
            continue
        description = str(item.get("description") or "").strip()
        language = str(item.get("language") or "").strip()
        stars = item.get("stargazers_count")
        details = [description]
        if language:
            details.append(f"主要语言：{language}")
        if isinstance(stars, int):
            details.append(f"Stars：{stars}")
        results.append(
            {
                "title": title,
                "url": url,
                "published_at": str(item.get("updated_at") or ""),
                "summary": "；".join(part for part in details if part),
                "source_type": "GitHub 仓库自述（只代表该仓库作者，不能自动视为官方结论）",
            }
        )
        if len(results) >= max(1, max_results):
            break
    return results


def _google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def _bing_news_rss_url(query: str) -> str:
    return f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"


def _bing_web_rss_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"


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
    mode: str = "auto",
    domains: list[str] | None = None,
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
        f"搜索类型：{mode}",
        f"聚合来源：{source_name}",
        "搜索结果如下。实时信息要结合发布时间判断时效性；一般网页可用于核验名称、出处和事实：",
    ]
    if domains:
        lines.insert(3, f"优先网站：{', '.join(domains)}")
    for index, result in enumerate(results, start=1):
        title = result.get("title") or "无标题"
        published_at = result.get("published_at") or "未标明"
        summary = _shorten(result.get("summary") or "无摘要", 220)
        url = result.get("url") or "无链接"
        source_type = result.get("source_type") or "一般网页/媒体摘要，需结合原文判断"
        lines.append(
            f"{index}. 标题：{title}\n"
            f"   来源性质：{source_type}\n"
            f"   发布时间：{published_at}\n"
            f"   摘要：{summary}\n"
            f"   URL：{url}"
        )
    return "\n".join(lines)


def _search_sources(query: str, mode: str) -> tuple[tuple[str, str], ...]:
    web = ("Bing Web", _bing_web_rss_url(query))
    google_news = ("Google News", _google_news_rss_url(query))
    bing_news = ("Bing News", _bing_news_rss_url(query))
    if mode == "news":
        return google_news, bing_news, web
    if mode in {"web", "research"}:
        return web, google_news, bing_news
    return web, google_news, bing_news


def _normalize_domains(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    domains: list[str] = []
    for raw in value[:3]:
        candidate = str(raw or "").strip().casefold()
        if "://" in candidate:
            candidate = urlsplit(candidate).hostname or ""
        candidate = candidate.strip(". ")
        if not re.fullmatch(r"[a-z0-9.-]{3,253}", candidate):
            continue
        if ".." in candidate or candidate.startswith("-") or candidate.endswith("-"):
            continue
        if candidate not in domains:
            domains.append(candidate)
    return domains


def _domain_scoped_query(query: str, domains: list[str]) -> str:
    if not domains:
        return query
    scoped = " OR ".join(f"site:{domain}" for domain in domains)
    return f"{query} ({scoped})"


def _filter_results_by_domains(
    results: list[dict[str, str]],
    domains: list[str],
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for result in results:
        hostname = (urlsplit(str(result.get("url") or "")).hostname or "").casefold().rstrip(".")
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            selected.append(result)
    return selected


def _domain_selected(domains: list[str], expected: str) -> bool:
    return any(domain == expected or domain.endswith(f".{expected}") for domain in domains)


def _deduplicate_results(
    results: list[dict[str, str]],
    max_results: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in results:
        url = str(result.get("url") or "").strip()
        title = str(result.get("title") or "").strip()
        key = (url or title).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(result)
        if len(selected) >= max(1, max_results):
            break
    return selected


async def _append_primary_source_excerpt(
    formatted_results: str,
    results: list[dict[str, str]],
    config: Any,
) -> str:
    if not results:
        return formatted_results
    url = str(results[0].get("url") or "").strip()
    if not url:
        return formatted_results
    try:
        from .web_page_tool import open_web_page

        page = await open_web_page({"url": url, "max_chars": 2800}, config)
    except Exception:
        return formatted_results
    if page.startswith("网页读取失败"):
        return formatted_results
    return (
        f"{formatted_results}\n\n"
        "已自动读取排名最高的原始来源，下面正文证据优先于搜索摘要：\n"
        f"{page}"
    )


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
