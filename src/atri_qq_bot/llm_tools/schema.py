from __future__ import annotations

from typing import Any

from ..voice.policy import load_voice_behavior


TOOL_INSTRUCTION_PROMPT = """你可以在需要时自主调用工具，但不要为了显得聪明而调用。

工具使用原则：
- get_current_time：当回答依赖当前日期、时间、星期、今天/明天/刚才/早晚等相对时间时使用。
- get_weather：用户询问某地当前天气、温度、降雨或近期天气预报时使用。不要用新闻搜索代替天气数据。
- search_web：当回答依赖实时变化的信息时使用，例如最新消息、新闻、价格、版本、政策、比赛结果、近期事件，或用户明确说“查一下/搜一下”时使用。
- speak_as_atri（仅在工具列表中出现时）：当用户明确想听语音、让你读一句话，或当前亲密场景用一小段语音会明显更自然时使用。用户要求唱歌时也必须调用，并把 mode 填为 singing；普通说话填 speech。普通聊天默认文字回复，不要频繁发语音。
- 用户明确要求发送或收听语音时，必须调用 speak_as_atri；私聊和允许语音的群聊都一样。禁止编造“群聊里不方便开麦”“现在不方便发语音”“害羞所以只发文字”等理由拒绝。
- 用户要求唱歌或哼唱时，禁止用歌词、动作描写或音乐符号假装已经唱过；必须调用 speak_as_atri 并设置 mode=singing。工具失败或没有真实歌声时应诚实说明，不能把普通朗读冒充歌唱。
- 调用 speak_as_atri 时，把真正想对用户说的话完整放进 text，并如实填写 reason：用户明确要求为 explicit_request，回应用户语音为 voice_reply，自主选择为 autonomous，主动消息为 proactive。
- 语音的 emotion 要服从这句话真正表达的情绪：安慰和亲近用 gentle，开心/得意/玩笑用 happy，害羞或撒娇用 shy，低落用 sad，认真提醒用 serious，困倦或晚安用 sleepy，惊讶用 surprised；没有明显情绪才用 neutral。intensity 通常取 0.45-0.75，只有非常明显的情绪才更高。
- offer_voice_call（仅在工具列表中出现时）：只在私聊中，用户明确想通话，或关系足够亲近且当前话题适合连续交谈时邀请通话。不要在用户忙碌、难受但未表达交流意愿、群聊或普通问答中突然邀请。
- 语音或通话工具成功后，最终回复不要复述工具中已经发送的内容；工具不可用时自然改用文字。
- 普通闲聊、情绪安慰、群聊接梗、角色互动，如果当前聊天上下文已经够用，不要调用搜索。
- 搜索结果必须按来源和发布时间判断时效性；如果结果没有明确发布时间，不要声称它一定是最新。
- 工具失败时不要编造结果，直接自然说明现在拿不到可靠实时信息。
"""


def available_tool_schemas(config: Any) -> list[dict[str, Any]]:
    if not bool(getattr(config, "llm_tools_enabled", True)):
        return []

    tools = [_current_time_schema()]
    if bool(getattr(config, "web_search_enabled", True)):
        tools.append(_weather_schema())
        tools.append(_web_search_schema(config))
    if bool(getattr(config, "voice_tts_enabled", False)):
        tools.append(_voice_schema(config))
        if load_voice_behavior().get("calls_enabled", False):
            tools.append(_voice_call_schema())
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
            "description": "搜索最新网页/新闻信息。仅当用户需要实时变化的信息，或明确要求查一下/搜一下时使用。",
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
                },
                "required": ["query"],
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
