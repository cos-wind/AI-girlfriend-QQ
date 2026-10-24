from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import hashlib
import io
import json
import re
import time
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..prompting import load_prompt
from ..runtime.inference_lock import InferencePriority, inference_resource_lease
from ..runtime.paths import PROJECT_ROOT
from ..runtime.services import ensure_ollama_service
from ..toolbox_parts import formatting as _toolbox_formatting
from ..toolbox_parts import media_probe as _toolbox_media_probe
from ..toolbox_parts import office_docs as _toolbox_office_docs
from ..toolbox_parts import request_collection as _toolbox_request_collection
from ..toolbox_parts.analysis_result import ToolAnalysisResult, _VisionModelResponse
from ..toolbox_parts.ocr import OcrExtraction, extract_image_text


URL_RE = re.compile(r"https?://[^\s<>\]）)\"']+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"'<>]+)")
TEXT_EXTENSIONS = {".txt", ".md", ".log", ".csv", ".tsv", ".json", ".py", ".js", ".ts", ".tsx",
                   ".jsx", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".tex", ".yaml", ".yml"}
DOC_EXTENSIONS = {".docx", ".pdf"}
SHEET_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | DOC_EXTENSIONS | SHEET_EXTENSIONS | IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv"}
MAX_TEXT_CHARS = 2800

VISUAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "direct_answer": {"type": "string"},
        "visible_text": {"type": "string"},
        "subjects": {"type": "string"},
        "identity": {"type": "string"},
        "emotion": {"type": "string"},
        "social_intent": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needs_web_verification": {"type": "boolean"},
        "search_keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "direct_answer",
        "visible_text",
        "subjects",
        "identity",
        "emotion",
        "social_intent",
        "evidence",
        "confidence",
        "needs_web_verification",
        "search_keywords",
    ],
    "additionalProperties": False,
}

OneBotActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]

from .documents import ToolboxDocumentsMixin
from .request import ToolboxRequestMixin
from .state import ToolboxStateMixin
from .video import ToolboxVideoMixin
from .vision import ToolboxVisionMixin


class ToolAnalyzer(
    ToolboxStateMixin,
    ToolboxRequestMixin,
    ToolboxDocumentsMixin,
    ToolboxVisionMixin,
    ToolboxVideoMixin,
):
    """对外保持原有材料分析入口，内部按材料类型拆分实现。"""


# Keep private helper names importable from atri_qq_bot.toolbox. Existing callers
# and tests use this module as the stable compatibility seam.
from . import helpers as _toolbox_helpers

for _name, _value in vars(_toolbox_helpers).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


__all__ = [
    "ToolAnalyzer",
    "ToolAnalysisResult",
    "_VisionModelResponse",
]
