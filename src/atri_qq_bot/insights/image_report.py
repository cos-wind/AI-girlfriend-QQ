"""把群聊总结绘制为可直接发送到 QQ 的竖版 PNG 长图。

这里不依赖浏览器截图，避免 NapCat/WebUI 运行环境没有 Chromium 时无法发送图文。
报告只绘制总结结构、文字和 QQ 头像，不把群友消息中的图片或内部文件名带入图片。
"""

from __future__ import annotations

import io
import math
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps


WIDTH = 1200
MARGIN = 58
PAPER = (253, 248, 240)
INK = (93, 81, 75)
MUTED = (155, 133, 123)
SKY = (212, 236, 247)
SKY_DEEP = (120, 188, 213)
APRICOT = (253, 235, 208)
PINK = (252, 228, 236)
MINT = (213, 245, 227)
CORAL = (239, 151, 121)
WHITE = (255, 253, 247)
_WINDOWS_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def group_summary_image_path(detail: dict[str, Any], directory: str | Path) -> Path:
    """为群聊总结生成稳定、可读且适用于 Windows 的 PNG 文件名。"""
    raw_time = str(detail.get("created_at") or detail.get("completed_at") or "").strip()
    try:
        generated_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if generated_at.tzinfo is not None:
            generated_at = generated_at.astimezone()
    except ValueError:
        generated_at = datetime.now().astimezone()
    timestamp = generated_at.strftime("%Y%m%d-%H%M%S")
    raw_group_name = str(detail.get("group_name") or f"群{detail.get('group_id') or '未知'}")
    group_name = _WINDOWS_FILENAME_RE.sub("", raw_group_name).strip(" .")[:80] or "未命名群聊"
    period_name = {"daily": "日报", "weekly": "周报", "monthly": "月报"}.get(
        str(detail.get("period_type") or "").lower(), "群聊总结"
    )
    summary_suffix = _WINDOWS_FILENAME_RE.sub("", str(detail.get("id") or ""))[:8]
    filename = f"{timestamp}_{group_name}_{period_name}"
    if summary_suffix:
        filename += f"_{summary_suffix}"
    return Path(directory).expanduser().resolve() / f"{filename}.png"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf" if bold else r"C:\Windows\Fonts\simsun.ttc",
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# 微软雅黑等中文字体缺少的表情/特殊符号，直接画会渲染成"方框"；渲染前移除。
_NO_TOFU_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001F300-\U0001F5FF\U0001D400-\U0001D7FF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)


def _no_tofu(value: Any) -> str:
    """剔除中文字体画不出来、会显示为方框的表情与装饰符号。"""
    return _NO_TOFU_RE.sub("", str(value or ""))


def _wrap(draw: ImageDraw.ImageDraw, value: Any, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    text = " ".join(_no_tofu(value).replace("\r", "").split()) or "暂无内容"
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or ["暂无内容"]


def _text_block(draw: ImageDraw.ImageDraw, value: Any, xy: tuple[int, int], font: ImageFont.FreeTypeFont,
                width: int, fill: tuple[int, int, int] = INK, line_gap: int = 8,
                max_lines: int | None = None) -> int:
    lines = _wrap(draw, value, font, width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("。；，") + "…"
    x, y = xy
    bbox = font.getbbox("群")
    line_height = bbox[3] - bbox[1] + line_gap
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _line_height(font: ImageFont.FreeTypeFont, line_gap: int = 8) -> int:
    """返回和 ``_text_block`` 一致的行高，供动态计算卡片高度。"""
    bbox = font.getbbox("群")
    return bbox[3] - bbox[1] + line_gap


def _draw_wave(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, color: tuple[int, int, int]) -> None:
    """绘制手账风细海浪线，避免依赖字体中的特殊波浪字符。"""
    points: list[tuple[int, int]] = []
    for offset in range(width + 1):
        # 两个柔和周期，形成不规则但连续的海浪线。
        value = 3.0 * math.sin(offset / 7.0) + 1.5 * math.sin(offset / 3.5)
        points.append((x + offset, int(y + value)))
    if len(points) > 1:
        draw.line(points, fill=color, width=2)


def _draw_clock(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int) -> None:
    """标题角落的迷你时钟装饰。"""
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=SKY_DEEP, width=2)
    draw.line((cx, cy, cx, cy - radius + 5), fill=CORAL, width=2)
    draw.line((cx, cy, cx + radius - 5, cy + 3), fill=CORAL, width=2)


def _draw_shell(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 20) -> None:
    """用线条画一个小贝壳，作为模块分隔装饰。"""
    draw.arc((x, y, x + size, y + size), 180, 360, fill=(225, 178, 158), width=2)
    for offset in (4, 9, 14):
        draw.line((x + size // 2, y + size // 2, x + offset, y + 2), fill=(225, 178, 158), width=1)


def _avatar(user_id: str, size: int) -> Image.Image | None:
    if not str(user_id).isdigit():
        return None
    try:
        request = Request(
            f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100",
            headers={"User-Agent": "ATRI-group-summary/1.0"},
        )
        with urlopen(request, timeout=2.5) as response:
            raw = response.read(256 * 1024)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        return ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
    except Exception:
        return None


def _rounded_image(base: Image.Image, image: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    x, y, right, bottom = box
    size = (right - x, bottom - y)
    image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS).convert("RGB")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    base.paste(image, (x, y), mask)


def _topic_title(value: Any, index: int) -> str:
    title = str(value or "").strip()
    if not title or title.lower().replace(" ", "") in {"atri", "亚托莉", "表情", "emoji", "闲聊", "日常讨论"}:
        return f"群聊重点讨论 {index + 1}"
    return title[:32]


def render_group_summary_image(detail: dict[str, Any], output_path: str | Path) -> Path:
    """生成一张适合 QQ 发送的长图，并返回实际文件路径。"""
    statistics = detail.get("statistics") if isinstance(detail.get("statistics"), dict) else {}
    sections = statistics.get("report_sections") if isinstance(statistics.get("report_sections"), dict) else {}
    period_type = str(detail.get("period_type") or "daily")
    period_name = {"daily": "日报", "weekly": "周报", "monthly": "月报"}.get(period_type, "群聊总结")
    group_name = str(detail.get("group_name") or "未命名群聊")

    # 先估算一个足够长的画布，最后按实际内容裁切。
    image = Image.new("RGB", (WIDTH, 9000), PAPER)
    draw = ImageDraw.Draw(image)
    title_font, section_font = _font(46, bold=True), _font(29, bold=True)
    body_font, small_font = _font(19), _font(15)
    y = 38

    # 奶白底纸上的细点和海浪线。
    for px in range(22, WIDTH, 30):
        for py in range(20, 9000, 30):
            draw.ellipse((px, py, px + 3, py + 3), fill=(235, 229, 220))

    draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + 158), radius=28, fill=WHITE, outline=SKY_DEEP, width=3)
    draw.rectangle((WIDTH // 2 - 95, y - 8, WIDTH // 2 + 95, y + 20), fill=(252, 210, 198))
    _draw_clock(draw, (WIDTH - MARGIN - 38, y + 42), 15)
    _draw_shell(draw, MARGIN + 28, y + 31, 22)
    draw.text((WIDTH // 2, y + 27), f"{group_name} · {period_name}", font=title_font, fill=CORAL, anchor="ma")
    draw.text((WIDTH // 2, y + 91), "亚托莉的群聊日记", font=section_font, fill=INK, anchor="ma")
    _draw_wave(draw, WIDTH // 2 - 92, y + 143, 184, SKY_DEEP)
    y += 190

    messages = int(detail.get("message_count") or 0)
    members = int(statistics.get("member_count") or len(statistics.get("active_members") or []))
    chars = int(statistics.get("total_characters") or 0)
    cards = [("消息", messages, "消息总数", CORAL), ("成员", members, "参与人数", (121, 201, 140)),
             ("字数", chars, "总字符数", (167, 120, 213)), ("时段", statistics.get("active_hours", 0), "活跃时段", SKY_DEEP)]
    card_w = (WIDTH - 2 * MARGIN - 36) // 4
    for index, (icon, value, label, color) in enumerate(cards):
        x = MARGIN + index * (card_w + 12)
        draw.rounded_rectangle((x, y, x + card_w, y + 122), radius=18, fill=WHITE, outline=SKY, width=2)
        # 用小圆点+文字代替 ▢♧✦◷ 等装饰符号，避免中文字体渲染成方框。
        cx = x + card_w // 2
        draw.ellipse((cx - 10, y + 18, cx + 10, y + 38), fill=color)
        draw.text((cx, y + 28), icon, font=_font(17, bold=True), fill=WHITE, anchor="mm")
        draw.text((cx, y + 53), str(value), font=_font(28, bold=True), fill=CORAL, anchor="ma")
        draw.text((cx, y + 96), label, font=small_font, fill=MUTED, anchor="ma")
    y += 150

    def section(title: str) -> None:
        nonlocal y
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + 58), radius=18, fill=WHITE, outline=SKY, width=2)
        draw.text((MARGIN + 24, y + 14), title, font=section_font, fill=INK)
        _draw_wave(draw, WIDTH - MARGIN - 155, y + 31, 105, SKY_DEEP)
        _draw_shell(draw, WIDTH - MARGIN - 35, y + 19, 18)
        y += 78

    section("① 群聊总览 · 活跃轨迹")
    activity_height = 390 if period_type == "daily" else 330
    draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + activity_height), radius=22, fill=WHITE, outline=(222, 212, 201), width=2)
    activity = statistics.get("hour_distribution") if period_type == "daily" else statistics.get("period_distribution")
    labels = [f"{i:02d}:00" for i in range(24)] if period_type == "daily" else list(statistics.get("period_distribution_labels") or [])
    if period_type == "weekly":
        labels = labels[:7] or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if period_type == "monthly":
        labels = labels[:8] or [f"第{i}周" for i in range(1, 9)]
    values = [int(v or 0) for v in list(activity or [])[:len(labels)]]
    values += [0] * max(0, len(labels) - len(values))
    maximum = max(values) or 1
    bar_h = 12 if len(labels) > 10 else 24
    step = 14 if len(labels) > 10 else 34
    for index, label in enumerate(labels):
        by = y + 18 + index * step
        if by + bar_h > y + activity_height - 18:
            break
        draw.text((MARGIN + 20, by - 2), str(label)[:12], font=small_font, fill=INK)
        left = MARGIN + 145
        right = WIDTH - MARGIN - 78
        draw.rounded_rectangle((left, by, right, by + bar_h), radius=bar_h // 2, fill=(244, 250, 249), outline=SKY, width=1)
        draw.rounded_rectangle((left, by, left + int((right - left) * values[index] / maximum), by + bar_h), radius=bar_h // 2, fill=CORAL if values[index] >= maximum * .7 else SKY_DEEP)
        draw.text((right + 12, by - 2), str(values[index]), font=small_font, fill=MUTED)
    y += activity_height + 22

    section("② 话题 Topics")
    topics = [item for item in (detail.get("topics") or []) if isinstance(item, dict)][:8]
    for index, topic in enumerate(topics):
        title = _topic_title(topic.get("title"), index)
        participants = "、".join(
            name for name in (_no_tofu(x).strip() for x in list(topic.get("participants") or [])[:8]) if name
        ) or "未识别"
        summary = topic.get("summary") or "；".join(str(x) for x in list(topic.get("samples") or [])[:2]) or "暂无文字摘要"
        opinion = topic.get("atri_view") or "亚托莉暂时没有足够信息形成额外判断。"
        topic_title_font = _font(24, bold=True)
        title_width = WIDTH - 2 * MARGIN - 48
        title_lines = _wrap(draw, f"☑ #{index + 1:02d} {title}", topic_title_font, title_width)
        if len(title_lines) > 2:
            title_lines = title_lines[:2]
            title_lines[-1] = title_lines[-1].rstrip("。；，") + "…"
        participant_lines = _wrap(draw, f"参与者：{participants}", small_font, title_width)
        if len(participant_lines) > 2:
            participant_lines = participant_lines[:2]
            participant_lines[-1] = participant_lines[-1].rstrip("、，") + "…"
        summary_lines = _wrap(draw, summary, body_font, title_width)
        if len(summary_lines) > 9:
            summary_lines = summary_lines[:9]
            summary_lines[-1] = summary_lines[-1].rstrip("。；，") + "…"
        opinion_width = WIDTH - 2 * MARGIN - 80
        opinion_lines = _wrap(draw, opinion, small_font, opinion_width)
        if len(opinion_lines) > 8:
            opinion_lines = opinion_lines[:8]
            opinion_lines[-1] = opinion_lines[-1].rstrip("。；，") + "…"
        bubble_text = str(opinion or "").strip()
        # 锐评若仍是后台/风控套话，或为空，就整块不画，避免展示一句模板口号。
        show_bubble = bool(bubble_text) and not any(
            marker in bubble_text
            for marker in ("数据侧", "从证据看", "建议把", "可以确认", "先拒绝", "分开记录", "排查", "符合认证口径", "长期记忆稳定")
        )
        title_lh = _line_height(topic_title_font, 5)
        small_lh = _line_height(small_font, 5)
        body_lh = _line_height(body_font, 8)
        bubble_height = (14 + small_lh + 4 + len(opinion_lines) * small_lh + 14) if show_bubble else 0
        height = (
            24 + len(title_lines) * title_lh + 8 + len(participant_lines) * small_lh
            + 10 + len(summary_lines) * body_lh + 16 + bubble_height + 18
        )
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + height), radius=22, fill=WHITE, outline=(222, 212, 201), width=2)
        draw.rectangle((MARGIN + 70, y - 6, MARGIN + 190, y + 17), fill=(249, 204, 184))
        title_y = y + 20
        _text_block(draw, f"☑ #{index + 1:02d} {title}", (MARGIN + 24, title_y), topic_title_font, title_width, max_lines=2, line_gap=5)
        participant_y = title_y + len(title_lines) * title_lh + 8
        _text_block(draw, f"参与者：{participants}", (MARGIN + 24, participant_y), small_font, title_width, fill=MUTED, line_gap=5, max_lines=2)
        summary_y = participant_y + len(participant_lines) * small_lh + 10
        _text_block(draw, summary, (MARGIN + 24, summary_y), body_font, title_width, max_lines=7)
        if show_bubble:
            bubble_top = summary_y + len(summary_lines) * body_lh + 16
            bubble_bottom = bubble_top + bubble_height
            draw.rounded_rectangle((MARGIN + 24, bubble_top, WIDTH - MARGIN - 24, bubble_bottom), radius=14, fill=SKY)
            draw.text((MARGIN + 40, bubble_top + 10), "亚托莉的小随笔", font=small_font, fill=(78, 143, 165))
            _text_block(draw, bubble_text, (MARGIN + 40, bubble_top + 10 + small_lh + 4), small_font, opinion_width, fill=INK, line_gap=5, max_lines=8)
        y += height + 16

    # 氛围随手记：把这一天最有人味、最好玩或最暖的瞬间写进来。
    vibe_paragraph = str(sections.get("vibe") or "").strip()
    vibe_rows: list[str] = []
    if vibe_paragraph:
        vibe_rows = _wrap(draw, vibe_paragraph, body_font, WIDTH - 2 * MARGIN - 48)
    else:
        for atm in (statistics.get("atmosphere") or [])[:4]:
            for sample in (atm.get("samples") or [])[:1]:
                if str(sample).strip():
                    vibe_rows.append(str(sample).strip())
        vibe_rows = vibe_rows[:4]
    if vibe_rows:
        section("③ 氛围随手记")
        vibe_text = "\n".join(vibe_rows)
        vibe_lines = _wrap(draw, vibe_text, body_font, WIDTH - 2 * MARGIN - 48)
        vibe_lh = _line_height(body_font, 8)
        vibe_h = 24 + len(vibe_lines) * vibe_lh + 20
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + vibe_h), radius=22, fill=WHITE, outline=(222, 212, 201), width=2)
        draw.rectangle((MARGIN + 70, y - 6, MARGIN + 170, y + 17), fill=(213, 238, 224))
        _text_block(draw, vibe_text, (MARGIN + 24, y + 20), body_font, WIDTH - 2 * MARGIN - 48, max_lines=6)
        y += vibe_h + 16

    section("④ 群友画像 · 活跃成员")
    active = [item for item in (statistics.get("active_members") or []) if isinstance(item, dict)][:8]
    highlights = {str(item.get("name")): item for item in list(sections.get("member_highlights") or []) if isinstance(item, dict)}
    message_total = max(1, int(statistics.get("message_count") or messages or 0))
    card_w = (WIDTH - 2 * MARGIN - 18) // 2
    for index in range(0, len(active), 2):
        row_items = active[index:index + 2]
        row_h = 254
        for col, member in enumerate(row_items):
            x = MARGIN + col * (card_w + 18)
            draw.rounded_rectangle((x, y, x + card_w, y + row_h), radius=20, fill=WHITE, outline=(222, 212, 201), width=2)
            avatar = _avatar(str(member.get("user_id") or ""), 66)
            if avatar:
                _rounded_image(image, avatar, (x + 20, y + 22, x + 86, y + 88), 33)
            else:
                draw.ellipse((x + 20, y + 22, x + 86, y + 88), fill=SKY)
                fallback_char = _no_tofu(str(member.get("nickname") or "群")).strip()[:1] or "群"
                draw.text((x + 53, y + 55), fallback_char, font=_font(25, bold=True), fill=WHITE, anchor="mm")
            name = _no_tofu(str(member.get("nickname") or "未知成员")).strip()[:16] or "群友"
            hl = highlights.get(name, {})
            if not hl and (name != str(member.get("nickname") or "")):
                hl = highlights.get(str(member.get("nickname") or ""), {})
            draw.text((x + 105, y + 25), name[:16], font=_font(21, bold=True), fill=INK)
            member_messages = int(member.get("messages") or 0)
            share_percent = float(member.get("share_percent") or (member_messages / message_total * 100.0))
            draw.text((x + 105, y + 55), f"{member_messages} 条 · 占 {share_percent:.1f}%", font=small_font, fill=MUTED)

            impression = _no_tofu(str(hl.get("atri_impression") or hl.get("evaluation") or "本时段在群里稳定参与，发言构成了重要的节奏。"))
            cursor = y + 92
            cursor = _text_block(draw, impression, (x + 20, cursor), small_font, card_w - 40, max_lines=2)

            behavior = [_no_tofu(b) for b in (hl.get("behavior") or []) if _no_tofu(b)]
            if behavior:
                cursor = _text_block(draw, " · ".join(behavior), (x + 20, cursor + 6), small_font, card_w - 40, fill=(167, 120, 213), max_lines=1)

            quote = [_no_tofu(q) for q in (hl.get("quote_style") or []) if _no_tofu(q)]
            if quote:
                cursor = _text_block(draw, "「" + quote[0][:60] + "」", (x + 20, cursor + 6), small_font, card_w - 40, fill=MUTED, max_lines=2)
            elif behavior:
                cursor = _text_block(draw, "（这次没抢到太多话，但一直在）", (x + 20, cursor + 6), small_font, card_w - 40, fill=MUTED, max_lines=1)

            stats = _no_tofu(str(hl.get("evaluation") or ""))
            if stats:
                _text_block(draw, stats, (x + 20, y + row_h - 30), small_font, card_w - 40, fill=MUTED, max_lines=1)
        y += row_h + 14
    if not active:
        draw.text((MARGIN + 20, y), "这一段时间还没有足够数据形成群友画像。", font=body_font, fill=MUTED)
        y += 50

    y += 24
    _draw_wave(draw, WIDTH // 2 - 92, y - 8, 184, SKY_DEEP)
    _draw_shell(draw, MARGIN + 30, y - 18, 20)
    _draw_shell(draw, WIDTH - MARGIN - 50, y - 18, 20)
    draw.text((WIDTH // 2, y), "~ 今天也是充实的一天呢 ~", font=section_font, fill=MUTED, anchor="ma")
    y += 70
    image = image.crop((0, 0, WIDTH, min(y, image.height)))
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    return output
