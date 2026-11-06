"""材料分析公共入口；实现文件直接声明依赖，不同步模块全局变量。"""
from __future__ import annotations

from atri_bot.toolbox.analysis_result import ToolAnalysisResult
from atri_bot.toolbox.request_collection import (
    ANALYZABLE_TEXT_EXTENSIONS as TEXT_EXTENSIONS,
    DOC_EXTENSIONS,
    IMAGE_EXTENSIONS,
    SHEET_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MaterialRef,
    MaterialRequest,
    MaterialResolver,
    collect_text_material,
)
from atri_bot.toolbox.documents import ToolboxDocumentsMixin
from atri_bot.toolbox.request import ToolboxRequestMixin
from atri_bot.toolbox.state import ToolboxStateMixin
from atri_bot.toolbox.video import ToolboxVideoMixin
from atri_bot.toolbox.vision import ToolboxVisionMixin


class ToolAnalyzer(
    ToolboxStateMixin,
    ToolboxRequestMixin,
    ToolboxDocumentsMixin,
    ToolboxVisionMixin,
    ToolboxVideoMixin,
):
    """规范化材料进入，按类型解析，输出带来源和局限的分析结果。"""


__all__ = [
    "ToolAnalyzer", "MaterialRef", "MaterialRequest", "MaterialResolver",
    "collect_text_material", "ToolAnalysisResult", "TEXT_EXTENSIONS",
    "DOC_EXTENSIONS", "SHEET_EXTENSIONS", "IMAGE_EXTENSIONS", "VIDEO_EXTENSIONS",
]
