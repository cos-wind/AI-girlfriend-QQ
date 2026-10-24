from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class _VisionModelResponse:
    content: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAnalysisResult:
    """多模态工具的统一结果对象。

    `findings` 保存可引用证据，`limitations` 保存能力边界；两者分开后，
    OCR 成功但视觉理解失败时仍能准确回复文字而不虚构画面。
    """

    category: str
    style: str
    sources: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    read_level: str = "full_content"
    visual_data: bytes | None = field(default=None, repr=False, compare=False)
    visual_source: str = ""
    visual_kind: str = ""
    visual_status: str = ""
    visual_ocr_confidence: float = 0.0
    # 视频降级链路提供了可引用的 OCR 或标题时，允许交给对话模型继续回答。
    # 图片视觉失败不设置此标记，继续保持原有的防幻觉静默保护。
    visual_fallback_available: bool = False
    # Archival evidence is deliberately excluded from prompt_context and repr.
    knowledge_materials: list[dict[str, Any]] = field(default_factory=list, repr=False, compare=False)

    # visual_data/visual_source 保存原始证据，status/limitations 描述证据边界；
    # 回复层据此区分“看到了画面”和“只识别到文字”，避免视觉失败后产生幻觉。
    def requires_visual_fail_safe(self) -> bool:
        return bool(
            self.visual_kind
            and self.visual_status in {"partial", "ocr_only", "metadata_only", "unavailable"}
            and not self.visual_fallback_available
        )

    def visual_failure_reply(self) -> str:
        """视觉失败只作为状态信号，不能伪造一条聊天回复。"""
        return ""

    def needs_grounding_repair(self, reply_text: str) -> bool:
        text = re.sub(r"\s+", "", str(reply_text or ""))
        if not text or self.read_level == "full_content":
            return False
        if self.requires_visual_fail_safe():
            allowed_ocr = "".join(
                finding.split("：", 1)[1]
                for finding in self.findings
                if finding.startswith("独立 OCR 文字：") and "：" in finding
            )
            visual_claims = (
                "画面里",
                "图里是",
                "图片里是",
                "人物是",
                "角色是",
                "看起来在",
                "表情是",
                "动作是",
            )
            if any(claim in text for claim in visual_claims):
                return True
            if "图中文字" in text and not allowed_ocr:
                return True
        if self.read_level == "partial_content":
            return any(
                claim in text
                for claim in ("看完整个", "看完视频", "读完全文", "完整内容里")
            )
        unread_content_claims = (
            "点开看了",
            "点进去看",
            "看完视频",
            "视频里说",
            "视频里讲",
            "画面里",
            "镜头里",
            "听完了",
            "听起来",
            "旋律",
            "音色",
            "字幕里",
            "全文里",
            "文档里写",
            "图片里",
            "图里",
            "盯着图",
            "瞄了眼",
            "看着图片",
            "看着表情",
            "看不太清",
            "看不清",
            "像素低",
            "太糊",
        )
        return any(claim in text for claim in unread_content_claims)

    def prompt_context(self) -> str:
        source_text = "；".join(self.sources[:6]) or "用户消息"
        finding_text = "\n".join(f"- {item}" for item in self.findings[:8]) or "- 暂无可用正文"
        limitation_text = "\n".join(f"- {item}" for item in self.limitations[:5]) or "- 无明显限制"
        visibility_rule = ""
        if self.read_level == "metadata_only":
            visibility_rule = (
                "\n可见性限制：本轮材料只读到标题、分享卡片、文件名、QQ 摘要或少量元数据；"
                "这不等于看完视频、看清图片、读完整文档或核验全部内容。"
                "回复时必须自然说明“我只能基于标题/卡片/摘要判断”，"
                "禁止说“我看完了视频”“视频里说”“我看到画面”“文档写了很多细节”等未读取事实。"
            )
        elif self.read_level == "partial_content":
            visibility_rule = (
                "\n可见性限制：本轮只读取到部分正文、公开简介、公开字幕或局部内容；"
                "可以基于可见部分分析，但必须避免断言完整视频/全文的未读细节。"
            )
        visual_rule = ""
        if self.visual_kind or any(
            item.startswith(("图片内容分析", "表情包情绪分析", "图片信息", "表情包信息"))
            for item in self.findings
        ):
            if self.requires_visual_fail_safe():
                visual_rule = (
                    "\n视觉证据状态：本轮没有取得可靠的完整画面理解。"
                    "只能复述明确列出的独立 OCR 或 QQ 摘要；禁止描述人物、动作、场景、"
                    "表情、颜色、身份或图片含义，禁止用聊天记忆补全。"
                    "应明确说本次识别不稳定，不得为了自然聊天而猜图。"
                )
            elif self.visual_fallback_available:
                visual_rule = (
                    "\n视觉结果状态：本轮视频没有取得完整可靠的画面理解，"
                    "但提供了可引用的 OCR 文字或视频标题。"
                    "只能基于这些明确证据回答；不要声称看清未读取的画面、动作或声音，"
                    "也不要用旧上下文补全视频内容。"
                    "如果用户问来源、最新进展或标题涉及具体事实，再按需使用联网搜索核验；"
                    "普通分享不必强行搜索。"
                )
            else:
                visual_rule = (
                    "\n以下视觉结果是本轮当前图片唯一可用的画面证据，优先级高于用户画像、兴趣、"
                    "旧图片、旧助手回复和此前聊天猜测。"
                    "回复时优先围绕当前画面或表情情绪回复。"
                    "人物身份、画中文字和画面细节只能来自本轮视觉结果或本轮联网核验，"
                    "不得用聊天记忆补全或改写。"
                    "\n用户问人物、文字、含义或情绪时必须直接回答，不要反问用户想让你识别还是描述。"
                    "视觉结果要求联网核验时直接使用搜索工具，不要先索要搜索许可。"
                )
        return (
            "你已获得用户发来的外部材料读取结果。不要说“我调用了工具”，不要输出技术流程；"
            "只把这些信息自然用于回答。"
            f"\n分类：{self.category}。"
            f"\n回复风格：{self.style}。"
            "\n风格要求：日常生活乐趣=轻松、有趣、可以短短吐槽；生活学术研究=准确、严谨、先给结论和依据。"
            "\n如果用户只是分享、让你看看或评价，就先给自然短评；如果用户要求深度分析、总结、数据分析或报告，就按结论、依据、风险/建议组织。"
            "\n禁止把没有读取到的内容编造成事实；不确定就说明只能基于当前可见信息判断。"
            f"{visibility_rule}"
            f"{visual_rule}"
            f"\n来源：{source_text}"
            f"\n可用信息：\n{finding_text}"
            f"\n限制：\n{limitation_text}"
        )

    def fallback_reply(self) -> str:
        """兼容旧接口；工具失败不再产生规则化用户回复。"""
        return ""


__all__ = ["ToolAnalysisResult"]
