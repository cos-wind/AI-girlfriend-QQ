from __future__ import annotations

import sys
from typing import Any


class OneBotServerMixin:
    def __getattribute__(self, name: str) -> Any:
        _sync_server_globals(self)
        return super().__getattribute__(name)


def _sync_server_globals(instance: Any) -> None:
    server_module = sys.modules.get("atri_qq_bot.onebot.server")
    if server_module is None:
        return
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        namespace = vars(module)
        for name, value in vars(server_module).items():
            if name != "OneBotServer" and not name.startswith("__"):
                namespace[name] = value

