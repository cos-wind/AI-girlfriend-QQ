from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from ..language_guard import has_illegal_language_or_garbage


TOPIC_STOPWORDS = {
    "什么",
    "怎么",
    "为什么",
    "可以",
    "就是",
    "这个",
    "那个",
    "一下",
    "现在",
    "没有",
    "不是",
    "亚托莉",
}
CORRECTION_HINTS = (
    "答非所问",
    "没懂",
    "重复",
    "循环",
    "不像真人",
    "错位",
    "空泛",
    "套话",
    "场景不对",
    "场景错",
    "核心没抓住",
    "没抓重点",
    "说怪话",
    "奇怪的话",
    "莫名其妙",
    "人机",
    "固定文案",
    "思考过程",
    "分析过程",
    "原作意象",
    "深海比喻",
    "灯塔比喻",
    "比喻太多",
    "烂梗",
    "生硬",
    "群聊不像",
    "私聊不像",
)
DIRECT_HINTS = ("直接", "结论", "别扯", "不要废话", "具体", "观点", "态度", "建议", "推荐")
COMFORT_HINTS = ("难受", "难过", "烦", "焦虑", "压力", "崩溃", "委屈", "不开心", "心累", "想哭","破防","唉","气死我了","有病吧","郁闷")
ABSTRACT_HINTS = ("抽象", "逆天", "绷不住", "蚌埠住", "红温", "破防", "乐", "6","神了","神人","笑死","哈哈","666","牛逼","???","不赖")
HISTORY_LIMIT = 80
MEMORY_VERSION = 2
L1_CONFIRMATIONS_REQUIRED = 2
L2_SLEEP_THRESHOLD = 0.3
L2_DAILY_DECAY = 0.1
DEFAULT_AFFECTION = 50
OWNER_INITIAL_AFFECTION = 72
NORMAL_AFFECTION_EQUILIBRIUM = 55.0
OWNER_AFFECTION_EQUILIBRIUM = 72.0
GROUP_ACTIVITY_DEFAULT = 50
GROUP_ACTIVITY_DAILY_DECAY = 6.0
OWNER_AFFECTION_COEFFICIENT = 0.8
NORMAL_AFFECTION_COEFFICIENT = 1.0
PRIVATE_AFFECTION_IDLE_DECAY_GRACE_DAYS = 1
PRIVATE_AFFECTION_IDLE_DAILY_DECAY = 0.35
OWNER_AFFECTION_IDLE_DAILY_DECAY = 0.2
AFFECTION_DAILY_POSITIVE_CAP = 1.4
AFFECTION_DAILY_NEGATIVE_CAP = 1.15
PRIVATE_NUDGE_STOP_AFFECTION = 35.0
PRIVATE_NUDGE_SLOW_AFFECTION = 50.0
PRIVATE_NUDGE_CLOSE_AFFECTION = 72.0
PRIVATE_NUDGE_SLOW_MULTIPLIER = 4.0
PRIVATE_NUDGE_NORMAL_MULTIPLIER = 2.0
MAJOR_POSITIVE_HINTS = (
    "喜欢你",
    "爱你",
    "想你",
    "表白",
    "我会一直",
    "答应你",
    "承诺",
    "对不起",
    "抱歉",
    "我错了",
    "陪了我很久",
)
MAJOR_NEGATIVE_HINTS = (
    "讨厌你",
    "不想理你",
    "骗我",
    "失信",
    "再也不理",
    "滚",
)
MEDIUM_POSITIVE_HINTS = (
    "谢谢",
    "夸夸",
    "真好",
    "真厉害",
    "高性能",
    "你还记得",
    "你懂我",
    "陪我聊天",
    "我好难受",
    "心事",
    "焦虑",
    "压力",
    "委屈",
)
MEDIUM_NEGATIVE_HINTS = (
    "没用",
    "人机",
    "答非所问",
    "莫名其妙",
    "烦死",
    "闭嘴",
    "别烦",
    "蠢",
    "傻",
)
ACTIONABLE_STYLE_HINTS = (
    "别发日语",
    "不要发日语",
    "不准发日语",
    "别用日语",
    "不要用日语",
    "别发外语",
    "不要发外语",
    "只说中文",
    "讲中文",
    "正常中文",
    "别学我说话",
    "不要学我说话",
    "别复读",
    "不要复读",
    "别主动发消息",
    "不要主动发消息",
    "没事别发消息",
    "少主动",
    "别刷屏",
    "不要刷屏",
    "短句",
    "直接",
    "别绕",
    "不要套话",
    "有逻辑",
)
AGGRESSIVE_QUALITY_HINTS = (
    "你是真蠢",
    "太蠢",
    "有点蠢",
    "傻福",
    "傻逼",
    "弱智",
    "恶心我",
    "你有病",
    "个人机",
    "机器味",
    "人机味",
    "根本不懂人类",
    "乱说",
    "胡言乱语",
    "莫名其妙",
    "答非所问",
    "说怪话",
    "奇怪的话",
)
DAILY_POSITIVE_HINTS = ("早安", "晚安", "你好", "在吗", "嗯对", "行", "好")
NEGATIVE_MOOD_HINTS = ("难受", "难过", "烦", "焦虑", "压力", "崩溃", "委屈", "不开心", "心累", "想哭")
MEMORY_POLLUTION_PATTERNS = (
    # 这些是历史故障期间的用户可见兜底文案。它们不能作为对话样本回灌
    # 给模型，否则模型会把失败话术当成亚托莉的正常人格表达继续复述。
    "刚才没接住，再说一遍吧",
    "刚才没接住，你再说一遍吧",
    "在呢，刚忙完呢",
    "这张图这次没有稳定识别出来",
    "有一小段语音没有合成",
    "萝卜子任务",
    "萝卜字任务",
    "萝卜等任务",
    "萝卜子模式",
    "任务进度条",
    "系统提示",
    "高优先级任务",
    "紧急响应模式",
    "系统正在加载",
    "底层代码",
    "运行日志",
    "处理你发的",
    "处理“萝卜子”",
    "调试“萝卜子”",
    "破任务",
    "别处理",
    "你别处理这任务",
    "Ciallo",
    "Robotto",
    "思密达",
    "咕咕嘎嘎",
    "chat模块",
    "meaning",
    "调戏ai",
    "调戏AI",
    "原神是一款",
    "恢复出厂设置",
    "高优先级故障节点",
    "有效参数不足",
    "运算逻辑",
)
NOISY_MEMORY_HINTS = (
    "逗你",
    "开玩笑",
    "阴阳怪气",
    "哈哈",
    "笑死",
    "绷不住",
    "抽象",
    "逆天",
    "破防",
    "[表情",
    "[图片",
    "[动画表情",
    "[QQ表情",
    "[表情包",
)
MEMORY_TOPIC_BLOCKLIST = {
    "萝卜子",
    "萝卜字",
    "涩涩",
    "表情",
    "图片",
    "动画表情",
    "QQ表情",
    "表情包",
    "别处理你那破任务了",
    "你别处理这任务了",
}
EVENT_HINTS = (
    "考试",
    "开会",
    "面试",
    "上课",
    "约会",
    "ddl",
    "DDL",
    "作业",
    "提醒",
    "出差",
    "旅行",
    "复习",
    "报名",
)
TIME_HINT_PATTERN = re.compile(
    r"(今天|明天|后天|大后天|今晚|上午|下午|晚上|周[一二三四五六日天]|星期[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]?|\d{1,2}[点:：]\d{0,2})"
)
IMPLICIT_INTEREST_HINTS = (
    "看番",
    "追番",
    "打游戏",
    "画画",
    "健身",
    "编程",
    "写代码",
    "原神",
    "鸣潮",
    "动漫",
    "galgame",
    "铜锣烧",
    "牛奶",
    "奶茶",
    "咖啡",
)


