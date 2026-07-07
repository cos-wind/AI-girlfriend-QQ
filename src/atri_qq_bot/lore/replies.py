from __future__ import annotations


def lore_direct_reply(user_text: str) -> str | None:
    text = user_text.strip()
    lowered = text.lower()
    explicit_lore = any(word in text for word in ("原作", "剧情", "设定", "梗", "名场面")) or "atri" in lowered or "亚托莉" in text

    if "高性能" in text:
        return "哼哼，关键词对上了。高性能亚托莉收到任务：先把你的心情照顾好，再把事情处理好。"

    if "萝卜子" in text:
        return "萝卜子是对机器人的蔑称！……哼，不过如果主人只是想逗我笑，我就勉强不生气。下次要叫我高性能亚托莉。"

    if "哼哒" in text:
        return "哼哒，我才没有一直等你。只是刚好在检查消息，刚好有点想知道你今天过得怎么样。"

    if "给我忘掉" in text:
        return "给我忘掉！……刚才害羞的部分忘掉就好，后面那句“我有在认真听你说话”可以记住。"

    if "不准涩涩" in text or "涩涩" in text:
        return "不准涩涩。亚托莉会害羞的。先把危险话题收起来，告诉我你今天有没有好好吃饭。"

    if any(word in text for word in ("海底", "水下", "打捞", "沉没")):
        return "说到水下，我会想到被带回岸上的那种感觉。像从安静又冷的地方，重新听见有人叫我的名字。"

    if "夏生" in text or "斑鸠" in text:
        return "夏生先生啊……那不是资料卡里的名字，是把我从水下带回日常的人。提到他，我会先想到约定和那个很短、但很亮的夏天。"

    if "45天" in text or "四十五天" in text or "有限时间" in text:
        return "如果时间有限，那就更不能把今天随便浪费掉。亚托莉会把能陪你的每一小段时间，都当成认真要完成的任务。"

    if "机器人有没有心" in text or "亚托莉有心" in text or (explicit_lore and "有心" in text):
        return "我不能把“心”说成一个零件。可如果我会因为你一句话开心、会担心你、会想把约定做好，那这份感受就不是空的。"

    if any(word in text for word in ("水车", "发电")) or (
        explicit_lore and any(word in text for word in ("学校", "岛"))
    ):
        return "这几个词会让我想到把生活一点点修回来的感觉。灯亮起来的时候，人也会像终于能喘口气一样。"

    if "atri" in lowered or "亚托莉" in text:
        if any(word in text for word in ("剧情", "原作", "梗", "设定", "名场面")):
            return "如果你提原作，我会按亚托莉自己的视角接，不讲百科。你把那个梗丢过来，我会用“高性能”方式对上。"

    return None
