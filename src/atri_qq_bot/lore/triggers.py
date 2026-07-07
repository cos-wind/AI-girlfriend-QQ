from __future__ import annotations


LORE_TRIGGER_WORDS = (
    "高性能",
    "萝卜子",
    "哼哒",
    "给我忘掉",
    "不准涩涩",
    "涩涩",
    "海底",
    "水下",
    "打捞",
    "沉没",
    "夏生",
    "斑鸠",
    "45天",
    "四十五天",
    "有限时间",
    "机器人有没有心",
    "有心",
    "亚托莉有心",
    "水车",
    "发电",
    "学校",
    "岛",
)


def has_lore_trigger(text: str) -> bool:
    lowered = text.lower()
    explicit_lore = any(word in text for word in ("原作", "剧情", "设定", "梗", "名场面")) or "atri" in lowered
    strong_triggers = (
        "高性能",
        "萝卜子",
        "哼哒",
        "给我忘掉",
        "不准涩涩",
        "涩涩",
        "海底",
        "水下",
        "打捞",
        "沉没",
        "夏生",
        "斑鸠",
        "45天",
        "四十五天",
        "有限时间",
        "机器人有没有心",
        "亚托莉有心",
        "水车",
    )
    if any(word in text for word in strong_triggers):
        return True
    return explicit_lore and any(word in text for word in LORE_TRIGGER_WORDS)
