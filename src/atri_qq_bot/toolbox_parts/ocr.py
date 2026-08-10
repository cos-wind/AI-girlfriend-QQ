from __future__ import annotations

import hashlib
import io
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OcrExtraction:
    text: str = ""
    average_confidence: float = 0.0
    error: str = ""
    line_count: int = 0
    frame_count: int = 0


_ENGINE: Any | None = None
_ENGINE_ERROR = ""
_ENGINE_LOCK = threading.Lock()
_CACHE: OrderedDict[str, OcrExtraction] = OrderedDict()
_CACHE_LIMIT = 48


def extract_image_text(
    data: bytes,
    *,
    minimum_confidence: float = 0.55,
    maximum_frames: int = 3,
) -> OcrExtraction:
    cache_key = (
        f"{hashlib.sha256(data).hexdigest()}:"
        f"{float(minimum_confidence):.3f}:{int(maximum_frames)}"
    )
    with _ENGINE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            _CACHE.move_to_end(cache_key)
            return cached

        engine, error = _ocr_engine()
        if engine is None:
            return OcrExtraction(error=error or "RapidOCR 未安装")

        candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
        try:
            prepared = _prepare_ocr_frames(data, maximum_frames=maximum_frames)
            for variant_index, (frame, tiny_source) in enumerate(prepared):
                result = engine(
                    frame,
                    text_score=max(0.45, min(0.95, minimum_confidence - 0.08)),
                )
                texts = tuple(getattr(result, "txts", ()) or ())
                confidences = tuple(getattr(result, "scores", ()) or ())
                for index, text in enumerate(texts):
                    normalized = " ".join(str(text or "").split()).strip()
                    if not normalized:
                        continue
                    try:
                        confidence = float(confidences[index])
                    except (IndexError, TypeError, ValueError):
                        confidence = 0.0
                    if not _plausible_ocr_candidate(
                        normalized,
                        confidence,
                        minimum_confidence=minimum_confidence,
                        tiny_source=tiny_source,
                    ):
                        continue
                    entry = candidates.setdefault(
                        normalized,
                        {
                            "score": confidence,
                            "variants": set(),
                            "order": len(candidates),
                        },
                    )
                    entry["score"] = max(float(entry["score"]), confidence)
                    entry["variants"].add(variant_index)
        except Exception as exc:
            extraction = OcrExtraction(error=f"{type(exc).__name__}: {exc}")
        else:
            ordered = sorted(candidates.items(), key=lambda item: int(item[1]["order"]))
            lines = [text for text, _ in ordered]
            scores = [float(meta["score"]) for _, meta in ordered]
            extraction = OcrExtraction(
                text="\n".join(lines),
                average_confidence=(
                    sum(scores) / len(scores)
                    if scores
                    else 0.0
                ),
                line_count=len(lines),
                frame_count=min(
                    max(1, maximum_frames),
                    _source_frame_count(data),
                ),
            )

        _CACHE[cache_key] = extraction
        _CACHE.move_to_end(cache_key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        return extraction


def _ocr_engine() -> tuple[Any | None, str]:
    global _ENGINE
    global _ENGINE_ERROR
    if _ENGINE is not None or _ENGINE_ERROR:
        return _ENGINE, _ENGINE_ERROR
    try:
        from rapidocr import RapidOCR

        _ENGINE = RapidOCR()
    except Exception as exc:
        _ENGINE_ERROR = f"{type(exc).__name__}: {exc}"
    return _ENGINE, _ENGINE_ERROR


def _prepare_ocr_frames(data: bytes, *, maximum_frames: int) -> list[tuple[bytes, bool]]:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        frame_count = int(getattr(image, "n_frames", 1) or 1)
        if frame_count > 1:
            indices = sorted({0, frame_count // 2, frame_count - 1})[
                : max(1, maximum_frames)
            ]
        else:
            indices = [0]

        frames: list[tuple[bytes, bool]] = []
        seen: set[str] = set()
        for index in indices:
            image.seek(index)
            source_frame = ImageOps.exif_transpose(image.copy())
            tiny_source = max(source_frame.size) < 96
            frame = source_frame.convert("RGB")
            longest = max(frame.size)
            if longest < 960:
                scale = min(4.0, 960 / max(1, longest))
                frame = frame.resize(
                    (
                        max(1, round(frame.width * scale)),
                        max(1, round(frame.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            elif longest > 2048:
                frame.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            variants = [frame]
            grayscale = ImageOps.autocontrast(ImageOps.grayscale(frame)).convert("RGB")
            variants.append(grayscale)
            for variant in variants:
                output = io.BytesIO()
                variant.save(output, format="PNG", optimize=True)
                prepared = output.getvalue()
                digest = hashlib.sha256(prepared).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                frames.append((prepared, tiny_source))
        return frames


def _source_frame_count(data: bytes) -> int:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            return max(1, int(getattr(image, "n_frames", 1) or 1))
    except Exception:
        return 1


def _plausible_ocr_candidate(
    text: str,
    confidence: float,
    *,
    minimum_confidence: float,
    tiny_source: bool,
) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized or confidence < minimum_confidence:
        return False
    visible = re.sub(r"\s+", "", normalized)
    if not visible or len(visible) > 500:
        return False
    informative = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", visible)
    if not informative:
        return False
    if len(visible) == 1 and confidence < 0.90:
        return False
    if tiny_source:
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", visible))
        alphanumeric_count = len(re.findall(r"[A-Za-z0-9]", visible))
        if confidence < 0.84:
            return False
        if not has_cjk and alphanumeric_count < 3:
            return False
    return True
