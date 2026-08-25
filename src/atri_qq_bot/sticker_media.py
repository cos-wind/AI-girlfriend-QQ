from __future__ import annotations

"""Prepare local sticker assets for the NapCat custom-sticker send path.

The source library is user-owned and must never be rewritten. Oversized assets
are resized into data/runtime/sticker-cache and the original file remains the
fallback when Pillow cannot decode an asset.
"""

import hashlib
from pathlib import Path

from PIL import Image, ImageSequence

from .runtime.paths import PROJECT_ROOT


STICKER_MAX_SIDE = 300
STICKER_CACHE_DIR = PROJECT_ROOT / "data" / "runtime" / "sticker-cache"
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def prepare_local_sticker(path: str | Path) -> str:
    """Return a QQ-sticker-sized local asset without changing the source file."""

    source = Path(path)
    if source.suffix.lower() not in _IMAGE_EXTENSIONS or not source.is_file():
        return str(source)

    try:
        with Image.open(source) as image:
            if max(image.size) <= STICKER_MAX_SIDE:
                return str(source)

            stat = source.stat()
            digest = hashlib.sha256(
                f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{STICKER_MAX_SIDE}".encode()
            ).hexdigest()[:16]
            cached = STICKER_CACHE_DIR / f"{digest}{source.suffix.lower()}"
            if cached.is_file() and cached.stat().st_size > 0:
                return str(cached)

            STICKER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if getattr(image, "n_frames", 1) > 1 and image.format == "GIF":
                _save_resized_gif(image, cached)
            else:
                _save_resized_static(image, cached)
            return str(cached) if cached.is_file() else str(source)
    except (OSError, ValueError):
        # A malformed resource should not break the reply chain. NapCat can
        # still report the original upload error, while normal resources work.
        return str(source)


def _resize_frame(frame: Image.Image) -> Image.Image:
    frame = frame.convert("RGBA")
    frame.thumbnail((STICKER_MAX_SIDE, STICKER_MAX_SIDE), Image.Resampling.LANCZOS)
    return frame.copy()


def _save_resized_gif(image: Image.Image, target: Path) -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for frame in ImageSequence.Iterator(image):
        frames.append(_resize_frame(frame))
        durations.append(max(20, int(frame.info.get("duration", image.info.get("duration", 100)))))

    if not frames:
        return
    frames[0].save(
        target,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=int(image.info.get("loop", 0)),
        disposal=2,
        optimize=True,
    )


def _save_resized_static(image: Image.Image, target: Path) -> None:
    frame = _resize_frame(image)
    suffix = target.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        frame.convert("RGB").save(target, format="JPEG", quality=88, optimize=True)
    elif suffix == ".webp":
        frame.save(target, format="WEBP", quality=88, method=4)
    else:
        frame.save(target, format="PNG", optimize=True)
