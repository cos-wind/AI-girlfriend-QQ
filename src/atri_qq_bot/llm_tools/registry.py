from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .time_tool import get_current_time
from .weather_tool import get_weather
from .web_page_tool import open_web_page
from .web_search_tool import search_web


ToolHandler = Callable[[dict[str, Any], Any], Awaitable[str]]


class ToolRegistry:
    """One execution seam for deterministic tools and test doubles.

    Context-specific actions such as speech delivery are intentionally not
    registered here: the conversation turn owns those action proposals.
    """

    def __init__(
        self,
        config: Any,
        handlers: Mapping[str, ToolHandler] | None = None,
    ) -> None:
        self._config = config
        self._handlers: dict[str, ToolHandler] = {
            "get_current_time": _current_time_handler,
            "get_weather": _weather_handler,
            "search_web": _web_search_handler,
            "open_web_page": _web_page_handler,
        }
        if handlers:
            self._handlers.update(handlers)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        handler = self._handlers.get(str(name or "").strip())
        if handler is None:
            return f"未知工具：{name}。不要编造这个工具的结果。"
        return await handler(arguments, self._config)


async def _current_time_handler(arguments: dict[str, Any], config: Any) -> str:
    del config
    return get_current_time(arguments)


async def _weather_handler(arguments: dict[str, Any], config: Any) -> str:
    if not bool(getattr(config, "web_search_enabled", True)):
        return "天气查询未启用。不要编造实时天气，可以说明当前无法获取天气数据。"
    return await get_weather(arguments, config)


async def _web_search_handler(arguments: dict[str, Any], config: Any) -> str:
    if not bool(getattr(config, "web_search_enabled", True)):
        return "联网搜索未启用。不要编造实时信息，可以说明当前不能搜索网页。"
    return await search_web(arguments, config)


async def _web_page_handler(arguments: dict[str, Any], config: Any) -> str:
    if not bool(getattr(config, "web_search_enabled", True)):
        return "网页读取未启用。不要编造页面内容。"
    return await open_web_page(arguments, config)
