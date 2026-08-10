from __future__ import annotations

from typing import Any

from ..prompting import load_prompt
from ..voice.policy import load_voice_behavior
from .agent_protocol import AGENT_ACTION_PROMPT, final_answer_schema


# 工具选择原则由外部 Markdown 维护，避免模型能力规则和代码实现重复。
_TOOL_USAGE_INSTRUCTION_PROMPT = load_prompt("tool_use")
AUTOMATIC_TOOL_INSTRUCTION_PROMPT = load_prompt("tool_use")
TOOL_INSTRUCTION_PROMPT = load_prompt("tool_use")

_LEGACY_AUTOMATIC_TOOL_INSTRUCTION_PROMPT = (
    "你可以在确有需要时自主调用工具；普通闲聊、情绪回应和已有上下文足够的问题直接回答，"
    "不要为了调用而调用工具。\n"
    + _TOOL_USAGE_INSTRUCTION_PROMPT
)
# 保留旧拼装变量仅供兼容导入；实际对外使用上面的外部文档内容。


def available_tool_schemas(config: Any) -> list[dict[str, Any]]:
    if not bool(getattr(config, "llm_tools_enabled", True)):
        return []

    tools = [_current_time_schema()]
    if bool(getattr(config, "web_search_enabled", True)):
        tools.append(_weather_schema())
        tools.append(_web_search_schema(config))
        tools.append(_web_page_schema())
    if bool(getattr(config, "voice_tts_enabled", False)):
        tools.append(_voice_schema(config))
        if load_voice_behavior().get("calls_enabled", False):
            tools.append(_voice_call_schema())
    if bool(getattr(config, "llm_agent_protocol_enabled", False)):
        tools.append(final_answer_schema(getattr(config, "max_tokens", 1200) * 4))
    return tools


def _current_time_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前本地时间、日期和星期。用户问现在、今天、明天、几点、星期几，或建议依赖当前时间时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "目标时区，默认 Asia/Shanghai。当前仅稳定支持 Asia/Shanghai、UTC 和 UTC±小时。",
                    }
                },
            },
        },
    }


def _web_search_schema(config: Any) -> dict[str, Any]:
    max_results = int(getattr(config, "web_search_max_results", 5) or 5)
    return {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索一般网页和最新新闻。用于实时信息、用户明确要求搜索，或核验视觉分析中不确定的人物、作品、梗图出处。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词。要具体，不要只传“最新消息”。",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"返回结果数量，默认不超过 {max_results} 条。",
                        "minimum": 1,
                        "maximum": max(1, max_results),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "web", "news", "research"],
                        "description": "一般资料用 web，近期消息用 news，前沿或未解问题用 research。",
                    },
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 3,
                        "description": "可选的强相关网站域名，例如 github.com、arxiv.org 或项目官网；不要填写完整 URL。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


def _web_page_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "open_web_page",
            "description": (
                "读取 search_web 返回的公开网页正文。用于核验具体事实、研究现状和原始来源；"
                "只打开搜索结果中确实出现的 URL。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "search_web 结果中的完整 http/https URL。",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    }


def _weather_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市或地区的当前天气与未来三天预报。天气、温度、降雨、体感温度问题优先使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "明确的城市或地区名称，例如“湖北十堰”或“东京”。不要猜测用户所在地。",
                    }
                },
                "required": ["location"],
            },
        },
    }


def _voice_schema(config: Any) -> dict[str, Any]:
    max_chars = max(20, int(getattr(config, "voice_max_chars", 160) or 160))
    return {
        "type": "function",
        "function": {
            "name": "speak_as_atri",
            "description": "让亚托莉用角色语音说一小段话。仅在用户想听语音或语音明显比文字更合适时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": f"要说出的完整口语文本，不含网址或舞台说明，最多 {max_chars} 字。",
                        "maxLength": max_chars,
                    },
                    "emotion": {
                        "type": "string",
                        "description": (
                            "这句话实际要表达的语气。neutral=平静，gentle=温柔安慰，"
                            "happy=开心/得意/玩笑，shy=害羞/撒娇，sad=低落，"
                            "serious=认真提醒，sleepy=困倦/晚安，surprised=惊讶。"
                        ),
                        "enum": [
                            "neutral",
                            "gentle",
                            "happy",
                            "shy",
                            "sad",
                            "serious",
                            "sleepy",
                            "surprised",
                        ],
                    },
                    "intensity": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": (
                            "情绪强度，普通自然口语建议 0.45-0.65，"
                            "明显情绪建议 0.65-0.8，避免无故填满。"
                        ),
                    },
                    "language": {
                        "type": "string",
                        "enum": ["auto", "zh", "ja", "en"],
                    },
                    "reason": {
                        "type": "string",
                        "enum": [
                            "explicit_request",
                            "voice_reply",
                            "autonomous",
                            "proactive",
                        ],
                        "description": "本次发语音的真实触发原因。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["speech", "singing"],
                        "description": "普通语音使用 speech；唱歌、哼唱使用 singing。",
                    },
                },
                "required": ["text", "reason"],
            },
        },
    }


def _voice_call_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "offer_voice_call",
            "description": "向当前私聊用户发起浏览器实时语音通话邀请。仅在用户明确要求或亲密且适合连续交谈时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "这次想聊的简短主题，可留空。",
                        "maxLength": 120,
                    }
                },
            },
        },
    }
