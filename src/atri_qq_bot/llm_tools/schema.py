from __future__ import annotations

from typing import Any


TOOL_INSTRUCTION_PROMPT = """你可以在需要时自主调用工具，但不要为了显得聪明而调用。

工具使用原则：
- get_current_time：当回答依赖当前日期、时间、星期、今天/明天/刚才/早晚等相对时间时使用。
- search_web：当回答依赖实时变化的信息时使用，例如最新消息、新闻、价格、版本、政策、天气、比赛结果、近期事件，或用户明确说“查一下/搜一下/现在怎么样”时使用。
- 普通闲聊、情绪安慰、群聊接梗、角色互动，如果当前聊天上下文已经够用，不要调用搜索。
- 搜索结果必须按来源和发布时间判断时效性；如果结果没有明确发布时间，不要声称它一定是最新。
- 工具失败时不要编造结果，直接自然说明现在拿不到可靠实时信息。
"""


def available_tool_schemas(config: Any) -> list[dict[str, Any]]:
    if not bool(getattr(config, "llm_tools_enabled", True)):
        return []

    tools = [_current_time_schema()]
    if bool(getattr(config, "web_search_enabled", True)):
        tools.append(_web_search_schema(config))
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
