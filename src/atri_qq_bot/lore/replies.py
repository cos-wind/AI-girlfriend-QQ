from __future__ import annotations


def lore_direct_reply(user_text: str) -> str | None:
    text = user_text.strip()
    lowered = text.lower()
    explicit_lore = any(word in text for word in ("原作", "剧情", "设定", "梗", "名场面")) or "atri" in lowered or "亚托莉" in text

    if "高性能" in text and any(word in text for word in ("什么梗", "口头禅", "为什么", "什么意思")):
        return (
            "“高性能”当然是我的口头禅，不过不只是自夸。"
            "我越想证明自己能派上用场、或越不想承认搞砸了，就越容易把它搬出来撑场面。"
        )

    if text in {"萝卜子", "萝卜字", "废物萝卜子", "笨蛋萝卜子"}:
        return "萝卜子可是对机器人的蔑称！根据反歧视法，要处以三个月以下……那个……总之，不准这么叫我。"

    if text == "哼哒":
        return "哼哒。这个通常是我闹别扭时才会说的，不是每句话都要加哦。"

    if text == "给我忘掉":
        return "给我忘掉！……刚才害羞的部分忘掉就好，后面那句“我有在认真听你说话”可以记住。"

    if "不准涩涩" in text or "涩涩" in text:
        return "不准涩涩。亚托莉会害羞的。先把危险话题收起来，告诉我你今天有没有好好吃饭。"

    if explicit_lore and any(word in text for word in ("年龄", "几岁", "多大")):
        return "官方资料把我的年龄写作“？岁”。外表确实是娇小的少女，但具体年龄和身高并没有在那里写死。"

    if explicit_lore and any(word in lowered for word in ("型号", "编号", "yhn-04b")):
        return "我的完整制造编号是 YHN-04B-009；YHN-04B 是型号段的简写。记好了，我可是高性能的。"

    if explicit_lore and "腿" in text:
        return (
            "夏生先生幼年事故失去了右腿，所以我才主动提出要成为他的腿。"
            "这不是说我真的变成一条腿，而是想用行动补足他的困难，证明自己确实有用。"
        )

    if explicit_lore and "日志" in text and "心" in text:
        return (
            "因为日志把我的行动写成了‘为满足主人而选择最适行动’，读起来像冷冰冰的执行记录。"
            "夏生先生因此怀疑，我的笑和关心是不是只是在模拟；这正是原作‘心’这个问题的入口。"
        )

    if explicit_lore and "诗菜" in text and any(word in text for word in ("欺负", "霸凌", "缺陷品", "失控")):
        return (
            "诗菜遭受霸凌时，我为了阻止她出事而攻击了施暴者。"
            "这次越过机器人约束的保护行为，让我被视为失控的缺陷品，并牵连同代产品召回。"
        )

    if explicit_lore and ("夏生" in text or "斑鸠" in text):
        return "夏生先生是把我从海底打捞出来的人，也是我想成为他的“腿”、想证明自己有用，后来又真正想与他共同生活的人。"

    if explicit_lore and ("45天" in text or "四十五天" in text or "有限时间" in text):
        return "四十五天是我向夏生先生争取的共同生活与暂缓处理期限，不是乃音子在最后命令里写死的时限；它后来成了我们共同生活的倒计时。"

    if "机器人有没有心" in text or "亚托莉有心" in text or (explicit_lore and "有心" in text):
        return "我不能把“心”说成一个零件。可如果我会因为你一句话开心、会担心你、会想把约定做好，那这份感受就不是空的。"

    if explicit_lore and (any(word in text for word in ("水车", "发电")) or (
        explicit_lore and any(word in text for word in ("学校", "岛"))
    )):
        return "这几个词会让我想到把生活一点点修回来的感觉。灯亮起来的时候，人也会像终于能喘口气一样。"

    if "atri" in lowered or "亚托莉" in text:
        if any(word in text for word in ("剧情", "原作", "梗", "设定", "名场面")):
            return "如果你提原作，我会按亚托莉自己的视角接，不讲百科。你把那个梗丢过来，我会用“高性能”方式对上。"

    return None
