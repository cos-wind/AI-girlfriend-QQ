from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse



URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"'<>]+)")
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv", ".tsv", ".json"}
# 文本路径沿用文档白名单；附件解析另支持源码，避免迁移扩大自动读取范围。
ANALYZABLE_TEXT_EXTENSIONS = TEXT_EXTENSIONS | {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".h", ".hpp",
    ".rs", ".go", ".java", ".tex", ".yaml", ".yml",
}
DOC_EXTENSIONS = {".docx", ".pdf"}
SHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        key = str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


@dataclass(frozen=True)
class MaterialRef:
    kind: str
    name: str = ""
    url: str = ""
    file: str = ""
    resource_id: str = ""
    summary: str = ""
    size: int | None = None

    @property
    def label(self) -> str:
        return self.name or self.summary or _basename_from_ref(self.url or self.file) or self.resource_id or self.kind


MaterialResolver = Callable[[MaterialRef], AsyncIterator[tuple[str, str]]]


@dataclass
class MaterialRequest:
    urls: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    file_refs: list[MaterialRef] = field(default_factory=list)
    image_refs: list[MaterialRef] = field(default_factory=list)
    video_refs: list[MaterialRef] = field(default_factory=list)
    share_hints: list[str] = field(default_factory=list)
    segment_limitations: list[str] = field(default_factory=list)
    has_image_only: bool = False

    @property
    def has_material(self) -> bool:
        return bool(
            self.urls
            or self.paths
            or self.file_refs
            or self.image_refs
            or self.video_refs
            or self.share_hints
            or self.segment_limitations
        )


def _plain_share_title(text: str, url: str) -> str:
    """Recognise platform-generated copy text, never an arbitrary user request.

    Keep the evidence next to this particular URL; another link or file in the
    message must not be imported by a worker processing just one source.
    """
    hostname = (urlparse(url).hostname or '').lower()
    platform = ('douyin' if hostname in {'douyin.com', 'www.douyin.com', 'v.douyin.com', 'www.iesdouyin.com'}
                else 'bilibili' if hostname in {'b23.tv', 'www.b23.tv', 'bilibili.com', 'www.bilibili.com'} else '')
    if not platform or url not in text:
        return ''
    prefix = text[:text.index(url)].rstrip()[-1000:]
    if platform == 'douyin':
        match = re.search(r'复制打开抖音[，,]\s*看看(【[^\r\n】]+的作品】[^\r\n]+)$', prefix)
    else:
        match = re.search(r'【([^\r\n】]+)-哔哩哔哩】$', prefix)
    return match[1].strip()[:500] if match else ''


def _material_filename_hint(ref: MaterialRef) -> str:
    for candidate in (ref.name, ref.file, ref.url, ref.summary, ref.resource_id):
        basename = _basename_from_ref(candidate)
        if Path(basename).suffix.lower() in SUPPORTED_FILE_EXTENSIONS | VIDEO_EXTENSIONS:
            return basename
    return ref.label


def _extension_for_material(name_or_url: str, content_type: str = "") -> str:
    suffix = Path(_basename_from_ref(name_or_url)).suffix.lower()
    if suffix in SUPPORTED_FILE_EXTENSIONS | VIDEO_EXTENSIONS:
        return suffix

    normalized_type = (content_type or "").split(";")[0].strip().lower()
    return {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
    }.get(normalized_type, "")

def _basename_from_ref(ref: str) -> str:
    ref = str(ref or "").strip()
    if not ref:
        return ""
    parsed = urlparse(ref)
    if parsed.scheme in {"http", "https"}:
        return unquote(Path(parsed.path).name)
    return unquote(Path(ref).name)

def _is_bilibili_url(url: str) -> bool:
    parsed = urlparse(url or "")
    domain = parsed.netloc.lower()
    return "bilibili.com" in domain or "b23.tv" in domain


def _extract_urls(text: str) -> list[str]:
    return [match.rstrip("，。！？!?") for match in URL_RE.findall(text or "")]

def _extract_paths(text: str) -> list[Path]:
    paths = []
    for match in WINDOWS_PATH_RE.findall(text or ""):
        cleaned = match.strip().rstrip("，。！？!?")
        suffix = Path(cleaned).suffix.lower()
        if suffix in TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            paths.append(Path(cleaned))
    return paths

def _classify_category(text: str, request: MaterialRequest) -> str:
    if request.image_refs or request.has_image_only:
        return "日常生活乐趣"
    if any(("bilibili.com" in urlparse(url).netloc.lower() or "b23.tv" in urlparse(url).netloc.lower()) for url in request.urls):
        if not any(word in text for word in ("论文", "研究", "数据", "报告", "权威", "引用", "指标", "统计")):
            return "日常生活乐趣"
    research_words = (
        "学术",
        "论文",
        "研究",
        "数据",
        "表格",
        "报告",
        "严谨",
        "准确",
        "权威",
        "实时",
        "资料",
        "引用",
        "来源",
        "指标",
        "统计",
        "总结",
    )
    if any(word in text for word in research_words):
        return "生活学术研究"
    if any(path.suffix.lower() in TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS for path in request.paths):
        return "生活学术研究"
    return "日常生活乐趣"


def collect_text_material(plain_text: str) -> MaterialRequest:
    """Extract explicit text links and paths without knowing any chat protocol."""
    request = MaterialRequest(urls=_dedupe(_extract_urls(plain_text)),
                              paths=_dedupe(_extract_paths(plain_text)))
    for url in request.urls:
        title = _plain_share_title(plain_text, url)
        if title:
            request.share_hints.append(f"用户分享标题：{title}")
    return request
