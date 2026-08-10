from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit


DEFAULT_WEB_PAGE_MAX_BYTES = 1_500_000
DEFAULT_WEB_PAGE_MAX_CHARS = 8_000
MAX_REDIRECTS = 3


async def open_web_page(
    arguments: dict[str, Any] | None = None,
    config: Any | None = None,
) -> str:
    args = arguments or {}
    current_url = validate_public_web_url(str(args.get("url") or ""))
    if not current_url:
        return "网页读取失败：URL 无效或指向本机/内网地址。"
    current_url = _prefer_readable_source_url(current_url)

    timeout = float(getattr(config, "web_search_timeout_seconds", 6.0) or 6.0)
    max_chars = max(
        1000,
        min(
            20_000,
            int(
                args.get("max_chars")
                or getattr(config, "web_page_max_chars", DEFAULT_WEB_PAGE_MAX_CHARS)
                or DEFAULT_WEB_PAGE_MAX_CHARS
            ),
        ),
    )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await _ensure_public_hostname(current_url)
                async with client.stream("GET", current_url, headers=_request_headers()) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = validate_public_web_url(urljoin(current_url, response.headers.get("location", "")))
                        if not target:
                            return "网页读取失败：页面跳转到了无效或不安全的地址。"
                        current_url = target
                        continue
                    response.raise_for_status()
                    content_type = str(response.headers.get("content-type") or "").casefold()
                    if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
                        return f"网页读取失败：暂不支持此内容类型（{content_type or '未知'}）。"
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        remaining = DEFAULT_WEB_PAGE_MAX_BYTES - total
                        if remaining <= 0:
                            break
                        chunks.append(chunk[:remaining])
                        total += min(len(chunk), remaining)
                        if total >= DEFAULT_WEB_PAGE_MAX_BYTES:
                            break
                    raw = b"".join(chunks)
                    text = raw.decode(response.encoding or "utf-8", errors="replace")
                extracted = extract_web_page_text(text)
                if not extracted:
                    return "网页读取失败：没有提取到可读正文。"
                return (
                    f"已读取网页：{current_url}\n"
                    "以下是网页中实际提取到的正文，只能依据这些内容回答；缺失的信息不要补造：\n"
                    f"{_shorten(extracted, max_chars)}"
                )
            return "网页读取失败：页面跳转次数过多。"
    except Exception as exc:
        return f"网页读取失败：{_short_error(exc)}。不要编造页面内容。"


def validate_public_web_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal", ".localhost")):
        return ""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not _is_public_ip(address):
        return ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path or "/", parsed.query, ""))


def _prefer_readable_source_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.hostname or "").casefold() != "github.com":
        return url
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return url
    owner, repository = parts[0], parts[1]
    if len(parts) >= 5 and parts[2] == "blob":
        branch = parts[3]
        file_path = "/".join(parts[4:])
        return f"https://raw.githubusercontent.com/{owner}/{repository}/{branch}/{file_path}"
    if len(parts) == 2:
        return f"https://raw.githubusercontent.com/{owner}/{repository}/HEAD/README.md"
    return url


async def _ensure_public_hostname(url: str) -> None:
    hostname = urlsplit(url).hostname or ""
    infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
    if not infos:
        raise ValueError("域名无法解析")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not _is_public_ip(address):
            raise ValueError("域名解析到了本机或内网地址")


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


class _ReadableHTMLParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    _BLOCK_TAGS = {"article", "main", "section", "div", "p", "br", "li", "h1", "h2", "h3", "h4", "table", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
        elif not self._skip_depth and lowered in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and lowered in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def extract_web_page_text(value: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(str(value or ""))
    text = html.unescape(" ".join(parser.parts))
    lines = []
    for line in re.split(r"[\r\n]+", text):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned and (not lines or cleaned != lines[-1]):
            lines.append(cleaned)
    return "\n".join(lines)


def _shorten(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _short_error(exc: Exception) -> str:
    return _shorten(re.sub(r"\s+", " ", str(exc).strip() or exc.__class__.__name__), 180)


def _request_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
    }
