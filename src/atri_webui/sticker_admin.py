from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from atri_qq_bot.runtime import STICKER_ROOT
from atri_qq_bot.stickers import IMAGE_EXTENSIONS


def sticker_summary() -> dict[str, Any]:
    STICKER_ROOT.mkdir(parents=True, exist_ok=True)
    folders = []
    for child in sorted(STICKER_ROOT.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        files = [
            sticker_file_payload(path)
            for path in sorted(child.rglob("*"), key=lambda p: p.name.lower())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        folders.append(
            {
                "name": child.name,
                "count": len(files),
                "path": str(child),
                "files": files[:80],
            }
        )
    return {"path": str(STICKER_ROOT), "folders": folders}


def sticker_file_payload(path: Path) -> dict[str, Any]:
    rel = path.relative_to(STICKER_ROOT).as_posix()
    return {
        "name": path.name,
        "path": rel,
        "size": path.stat().st_size,
        "url": f"/api/stickers/file?path={url_escape(rel)}",
    }


def sanitize_category(value: str) -> str:
    value = value.strip().replace("\\", "_").replace("/", "_")
    if not value or value.startswith("."):
        return ""
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,40}", value):
        return ""
    if value.lower() in {"con", "prn", "aux", "nul"}:
        return ""
    return value


def safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    name = re.sub(r"[^\w\-.()\u4e00-\u9fff]+", "_", name)
    return name[:120] or f"sticker_{int(time.time())}.jpg"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def looks_like_image_bytes(data: bytes, suffix: str) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def resolve_under(root: Path, rel: str) -> Path | None:
    try:
        rel = unquote(rel).replace("\\", "/").lstrip("/")
        path = (root / rel).resolve()
        root_resolved = root.resolve()
        if path == root_resolved or root_resolved in path.parents:
            return path
    except Exception:
        return None
    return None


def url_escape(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
