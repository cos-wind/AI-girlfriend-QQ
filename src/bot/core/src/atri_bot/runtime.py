"""Core lifecycle, independent of a desktop window or QQ transport.

Conversation services and tools live in this package; configuration lives in atri_shared.
The facade is passive; the engine and tools are created only on first use.
"""
from __future__ import annotations

from typing import Any


class BotRuntime:
    def __init__(self, config: Any, *, engine_factory=None, tools_factory=None):
        self.config = config
        self._engine_factory = engine_factory
        self._tools_factory = tools_factory
        self._engine = None
        self._tools = None

    @property
    def reply_engine(self):
        if self._engine is None:
            factory = self._engine_factory
            if factory is None:
                from .persona import AtriReplyEngine
                factory = AtriReplyEngine
            self._engine = factory(self.config)
        return self._engine

    @property
    def tools(self):
        if self._tools is None:
            factory = self._tools_factory
            if factory is None:
                from atri_bot.toolbox import ToolAnalyzer
                factory = ToolAnalyzer
            self._tools = factory(self.config)
        return self._tools


async def serve(config: Any, *, runtime=None):
    """Explicit API launch; never opens a QQ socket or starts an external app."""
    import asyncio
    from .api import bind_loop, start_core_api, stop_core_api

    bind_loop(asyncio.get_running_loop())
    httpd = await start_core_api(config, runtime if runtime is not None else BotRuntime(config))
    if httpd is None:
        raise RuntimeError("核心 API 未启用或监听失败，请检查本地端口与配置")
    try:
        await asyncio.Future()
    finally:
        await stop_core_api(httpd)

