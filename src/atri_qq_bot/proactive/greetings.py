from __future__ import annotations

import random
from datetime import datetime


MORNING_GREETINGS = (
    "早上好。高性能亚托莉把今日启动按钮交给你：先完成一件小事，心情就会跟着发光。",
    "早安，新的早晨到站。今天也从一个轻快的小目标开始吧，亚托莉会在这里给你加满元气。",
    "早上好。窗外是清晨模式，心情也切到前进档吧。今天先稳稳迈出第一步，就已经很厉害了。",
    "早安。空气像刚被洗过一样清亮，今天也要带着一点勇气出发。高性能亚托莉祝你一路顺利。",
    "7 点半到啦。把困意收进抽屉，带着元气给今天开个漂亮的头吧。亚托莉相信你可以把小事一件件做好。",
    "早上好，今日任务开始。先喝水、伸个懒腰，再把第一件事启动起来；好心情会跟着你一起上线。",
)


def morning_greeting_text(now: datetime | None = None) -> str:
    text = random.choice(MORNING_GREETINGS)
    if now and now.weekday() == 0:
        return f"早安。{text.removeprefix('早上好。').removeprefix('早安，')}"
    return text
