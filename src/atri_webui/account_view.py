"""WebUI 的"查看账号"选择。

## 为什么这是**只读**选择，而不是"切换运行账号"

面板可以手动选一个账号来**看**它的记忆与数据；但**机器人实际运行哪个账号仍然由
NapCat 决定**（`probe_onebot_status` → `follow_napcat_account`）。

反过来做——让面板的选择去改运行账号——是危险的：NapCat 登录的是 Y，机器人却按 X
运行，于是收到的全是 Y 的事件、写进的却是 X 的库。这正是整个账号系统要防的静默串号。

所以这里只有两种状态：

* ``auto``（默认）：查看账号 = 运行账号。读写都在运行账号上，功能与今天完全一致。
* 指定 ``account_id``：**只读检视模式**。读路径跟随该账号，写路径一律拒绝
  （见 :func:`is_read_only`），并记一条 warn 日志。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atri_qq_bot.runtime.paths import WEBUI_DIR

LOGGER = logging.getLogger("atri.webui.account_view")

AUTO = "auto"

VIEW_PATH = WEBUI_DIR / "account_view.json"


def load_view_selection() -> str:
    """读取面板的查看选择；读不出来或**值不可用**一律回落 ``auto``。

    只返回两种东西：``auto``，或一个 ``qq:`` 前缀的账号 ID。存储被手工改坏、
    或写了旧格式时，宁可回落默认也不要交出一个解析不了的字符串——
    ``str(123)`` 得到 ``"123"`` 这种"看起来像值"的垃圾正是要挡住的。
    """
    try:
        payload = json.loads(VIEW_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AUTO
    if not isinstance(payload, dict):
        return AUTO
    value = payload.get("view")
    if not isinstance(value, str):
        return AUTO
    cleaned = value.strip()
    if cleaned == AUTO:
        return AUTO
    if cleaned.startswith("qq:") and cleaned[3:].isdigit():
        return cleaned
    return AUTO


def save_view_selection(value: str) -> str:
    """保存查看选择。``"auto"`` 或账号 ID；非法值一律存成 ``auto``。"""
    wanted = str(value or "").strip()
    if wanted != AUTO and not wanted:
        wanted = AUTO
    if wanted != AUTO and not wanted.startswith("qq:"):
        raise ValueError(f"查看账号选择非法：{value!r}")

    VIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = VIEW_PATH.with_name(f"{VIEW_PATH.name}.tmp")
    temporary.write_text(
        json.dumps({"view": wanted}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(VIEW_PATH)
    return wanted


def is_read_only(view_selection: str, running_account_id: str | None) -> bool:
    """当前是否为只读检视模式。

    只有"明确选了某个账号，且它不是正在运行的那个"才算。选 ``auto`` 或者恰好选中
    运行账号时都不是只读——保持今天的完整功能。
    """
    value = str(view_selection or "").strip()
    if value == AUTO or not value:
        return False
    return value != str(running_account_id or "")


def describe(view_selection: str, running_account_id: str | None) -> dict[str, Any]:
    """给面板用的状态描述。"""
    value = str(view_selection or "").strip() or AUTO
    return {
        "selection": value,
        "is_auto": value == AUTO,
        "read_only": is_read_only(value, running_account_id),
    }


__all__ = [
    "AUTO",
    "VIEW_PATH",
    "describe",
    "is_read_only",
    "load_view_selection",
    "save_view_selection",
]
