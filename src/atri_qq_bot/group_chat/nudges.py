from __future__ import annotations

import random
from typing import Any


def group_nudge_text(profile: dict[str, Any] | None = None) -> str:
    choices = (
        "高性能亚托莉路过一下，只插一句。你们继续，我不抢话。",
        "群聊检测启动。哼哒，有人要开个话题吗？",
        "亚托莉轻量上线。没人说话的话，我就默认大家都在认真生活。",
        "今天有什么离谱事可以分享吗？我负责短短锐评一句。",
        "没人说话我就先待机。需要了再叫我。",
    )
    return random.choice(choices)
