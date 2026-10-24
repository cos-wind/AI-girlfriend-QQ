"""受约束的联网搜索工具。

搜索工具返回带来源的文本证据，而不是直接替模型生成答案。不同模式选择
新闻、网页、arXiv/GitHub 等强相关来源，并对结果数量、超时和域名做边界控制。
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus, urlsplit


DEFAULT_SEARCH_TIMEOUT_SECONDS = 6.0
DEFAULT_SEARCH_MAX_RESULTS = 5

# Bing News RSS 已于 2026 年被下线（返回搜索首页 HTML 而非 RSS），不再作为来源。
# 当前可靠的免费来源：Bing Web RSS（text/xml，实测可用）+ Google News RSS（兜底）。
# SearXNG 提供 JSON 接口（format=json），但公共实例在国内常被墙；通过环境变量
# ATRI_SEARXNG_INSTANCES 配置自托管实例可启用，未配置时自动跳过。
_SEARXNG_INSTANCES = tuple(
    inst.strip().rstrip("/")
    for inst in __import__("os").environ.get("ATRI_SEARXNG_INSTANCES", "").split(",")
    if inst.strip()
)


async def search_web(arguments: dict[str, Any] | None = None, config: Any | None = None) -> str:
    if not getattr(config, "web_search_enabled", True):
        return "搜索未执行：联网搜索已关闭。"
    # 先规范化 query/mode/domains，再选择来源；这样“最新消息”和“研究现状”
    # 走不同的来源集合，减少把普通网页结果误当成前沿研究结论。
    args = arguments or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return "搜索失败：缺少搜索关键词。"

    mode = str(args.get("mode") or "auto").strip().casefold()
    if mode not in {"auto", "web", "news", "research"}:
        mode = "auto"
    domains = _normalize_domains(args.get("domains"))
    # RSS 源不支持 site: 语法（会返回空结果），domain 过滤改由后置 URL 匹配完成。
    # 仅 SearXNG 之外保留 domain_scoped 查询的语义说明；实际 RSS 用原始 query。

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
            # 英文/技术术语查询在国内市场下（Bing 锁中文、Google News 中文市场召回为空）
            # 极易跑偏或空结果。arXiv/GitHub 是唯一不受语言市场锁定的稳定英文源，
            # 因此英文 query 的非 research 模式也先尝试它们兜底。
            if mode in {"web", "auto"} and _is_mostly_ascii(query) and not (
                getattr(config, "tavily_api_key", "") or getattr(config, "serpapi_api_key", "")
                or getattr(config, "searxng_instances", "")
            ):
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
            # 结构化搜索 API（Tavily/SerpAPI）召回质量最高，优先尝试；
            # 再走 SearXNG JSON（结构化、解析稳定），最后回退 RSS。
            tavily_key = str(getattr(config, "tavily_api_key", "") or "").strip()
            serpapi_key = str(getattr(config, "serpapi_api_key", "") or "").strip()
            if tavily_key:
                tavily_results, tavily_source = await _search_tavily(
                    client, query, max_results, domains, tavily_key
                )
                if tavily_results:
                    formatted = format_search_results(
                        query,
                        tavily_results,
                        source_name=tavily_source,
                        mode=mode,
                        domains=domains,
                    )
                    if mode in {"web", "auto"}:
                        return await _append_primary_source_excerpt(formatted, tavily_results, config)
                    return formatted
            if serpapi_key:
                serpapi_results, serpapi_source = await _search_serpapi(
                    client, query, max_results, domains, serpapi_key
                )
                if serpapi_results:
                    formatted = format_search_results(
                        query,
                        serpapi_results,
                        source_name=serpapi_source,
                        mode=mode,
                        domains=domains,
                    )
                    if mode in {"web", "auto"}:
                        return await _append_primary_source_excerpt(formatted, serpapi_results, config)
                    return formatted
            searxng_results, searxng_source = await _search_searxng(
                client, query, max_results, domains,
                instances=tuple(s.strip().rstrip("/") for s in str(config.searxng_instances).split(",") if s.strip())
                if config is not None and hasattr(config, "searxng_instances") else None,
            )
            if searxng_results:
                formatted = format_search_results(
                    query,
                    searxng_results,
                    source_name=searxng_source,
                    mode=mode,
                    domains=domains,
                )
                if mode in {"web", "auto"}:
                    return await _append_primary_source_excerpt(formatted, searxng_results, config)
                return formatted
            for source_name, url in _search_sources(query, mode):
                try:
                    response = await client.get(url, headers=_request_headers())
                    response.raise_for_status()
                    results = parse_news_rss(response.text, max_results)
                    if domains:
                        results = _filter_results_by_domains(results, domains)
                    if results:
                        formatted = format_search_results(
                            query,
                            results,
                            source_name=source_name,
                            mode=mode,
                            domains=domains,
                        )
                        # 网页/自动模式也自动读排名最高的原始来源正文，把"新闻摘要"升级成
                        # 可核验的证据——只回标题+一句话是专业问题答不出细节的主要原因。
                        if mode in {"web", "auto"}:
                            return await _append_primary_source_excerpt(formatted, results, config)
                        return formatted
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
            arxiv_query = _arxiv_and_query(compact_query)
            response = await client.get(
                "https://export.arxiv.org/api/query",
                params={
                    # arXiv 的 all: 多词是 OR 语义，需显式 AND 才能精准召回；
                    # 此前用 all:compact_query 导致多词 query 召回大量无关论文。
                    "search_query": arxiv_query,
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
        "new",
        "news",
        "dead",
        "the",
        "and",
        "for",
        "with",
        "what",
        "how",
        "why",
    }
    # 保留有区分度的词（含数字/连字符的技术编号，或非停用词的实义词），
    # 最多 4 个，用 AND 语义检索。此前对多词 query 只取首个词，召回大量无关论文。
    kept = [token for token in tokens if token.casefold() not in stopwords]
    return " ".join(kept[:4] or tokens[:3] or [str(query or "").strip()])


def _arxiv_and_query(compact_query: str) -> str:
    """把紧凑关键词转成 arXiv 的显式 AND 检索。

    arXiv API 的 `all:词1 词2` 是 OR 语义，多词会召回大量无关结果；
    用 `all:词1 AND all:词2` 显式 AND 才能精准命中。单短语则保留原样。
    """
    terms = [term for term in (compact_query or "").split() if term]
    if not terms:
        return 'all:""'
    if len(terms) == 1:
        return f'all:"{terms[0]}"'
    return " AND ".join(f'all:"{term}"' for term in terms)


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
    # Google News 会按 gl/hl 参数锁定语言市场：纯英文/技术术语查询若走中文市场
    # （gl=CN&hl=zh-CN）会召回为空，需切到英文市场（gl=US&hl=en）才能命中。
    if _is_mostly_ascii(query):
        return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def _is_mostly_ascii(query: str) -> bool:
    """判断 query 是否以英文/数字为主（用于选择英文市场）。"""
    letters = [ch for ch in str(query or "") if ch.isalpha() or ch.isdigit()]
    if not letters:
        return False
    ascii_count = sum(1 for ch in letters if ord(ch) < 128)
    return ascii_count / len(letters) >= 0.5


def _bing_web_rss_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"


async def _search_tavily(
    client: Any,
    query: str,
    max_results: int,
    domains: list[str],
    api_key: str,
) -> tuple[list[dict[str, str]], str]:
    """通过 Tavily Search API 搜索（结构化 JSON，专为 LLM 设计）。

    返回 title/url/content 结构，召回质量远高于 RSS（尤其游戏术语、热梗等
    垂直内容）。失败返回空列表，由上层回退到其它源。
    """
    try:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                # 保留图片/回答等字段关闭，只取文本结果，控制回执体积。
                "include_answer": False,
                "include_images": False,
            },
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return [], ""
        results: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = _clean_text(str(item.get("title") or ""))
            if not url and not title:
                continue
            results.append(
                {
                    "title": title or "无标题",
                    "url": url,
                    "published_at": str(item.get("published_date") or ""),
                    "summary": _clean_text(str(item.get("content") or "")),
                    "source_type": "Tavily 结构化搜索结果（含正文摘要，可作较可靠证据）",
                }
            )
            if len(results) >= max(1, max_results):
                break
        if domains:
            results = _filter_results_by_domains(results, domains)
        return results, "Tavily"
    except Exception:
        return [], ""


async def _search_serpapi(
    client: Any,
    query: str,
    max_results: int,
    domains: list[str],
    api_key: str,
) -> tuple[list[dict[str, str]], str]:
    """通过 SerpAPI 的 Google 引擎搜索（结构化 JSON）。

    中文市场下对热梗、时事等召回准确（百度百科/新华网等真实来源）。
    """
    try:
        response = await client.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "hl": "zh-cn",
                "gl": "cn",
                "num": max_results,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            return [], ""
        items = payload.get("organic_results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return [], ""
        results: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            title = _clean_text(str(item.get("title") or ""))
            if not url and not title:
                continue
            snippet = str(item.get("snippet") or "")
            date = str(item.get("date") or "")
            results.append(
                {
                    "title": title or "无标题",
                    "url": url,
                    "published_at": date,
                    "summary": _clean_text(snippet),
                    "source_type": "SerpAPI 结构化搜索结果（含摘要，可作较可靠证据）",
                }
            )
            if len(results) >= max(1, max_results):
                break
        if domains:
            results = _filter_results_by_domains(results, domains)
        return results, "SerpAPI"
    except Exception:
        return [], ""


async def _search_searxng(
    client: Any,
    query: str,
    max_results: int,
    domains: list[str],
    *, instances: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """通过 SearXNG 实例搜索（format=json）。实例来自环境变量，未配置返回空。"""
    active_instances = _SEARXNG_INSTANCES if instances is None else instances
    if not active_instances:
        return [], ""
    for instance in active_instances:
        try:
            response = await client.get(
                f"{instance}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": "zh-CN",
                },
                headers={**_request_headers(), "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            results = parse_searxng_results(payload, max_results)
            if domains:
                results = _filter_results_by_domains(results, domains)
            if results:
                return results, f"SearXNG ({instance})"
        except Exception:
            continue
    return [], ""


def parse_searxng_results(payload: Any, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
    items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    results: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = _clean_text(str(item.get("title") or ""))
        if not url and not title:
            continue
        results.append(
            {
                "title": title or "无标题",
                "url": url,
                "published_at": str(item.get("publishedDate") or ""),
                "summary": _clean_text(str(item.get("content") or "")),
            }
        )
        if len(results) >= max(1, max_results):
            break
    return results


def parse_news_rss(text: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS) -> list[dict[str, str]]:
    stripped = (text or "").lstrip()
    if not stripped or stripped.startswith("<!doctype") or stripped.startswith("<html"):
        # 来源可能下线 RSS 接口而改返回 HTML 页面，直接视为无结果而非抛解析异常。
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    results: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        published_at = _clean_text(item.findtext("pubDate") or "")
        summary = _clean_text(item.findtext("description") or "")
        if not title and not summary:
            continue
        url = _resolve_rss_link(link, item)
        results.append(
            {
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": summary,
            }
        )
        if len(results) >= max(1, max_results):
            break
    return results


def _resolve_rss_link(link: str, item: Any) -> str:
    """解析 RSS item 的真实链接。

    Google News RSS 的 <link> 是 news.google.com/rss/articles/... 重定向链接，
    open_web_page 读不到正文；此时改用 <source url="..."> 里的真实来源站
    （虽然多为站点首页，但至少是可访问的真实来源，优于无法跟踪的重定向）。
    """
    if link and "news.google.com/rss/articles" not in link:
        return link
    source = item.find("source")
    source_url = (source.get("url") or "").strip() if source is not None else ""
    if source_url:
        return source_url
    return link


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
    if mode == "news":
        return google_news, web
    if mode in {"web", "research"}:
        return web, google_news
    return web, google_news


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
    if not url or "news.google.com/rss/articles" in url:
        # 重定向链接无法直接读正文，跳过，避免白费一次网页读取。
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
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
