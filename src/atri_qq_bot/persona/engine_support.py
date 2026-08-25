from __future__ import annotations

import sys
from typing import Any


class PersonaEngineMixin:
    """让拆分后的实现继续读取 core.py 的稳定运行时依赖。"""

    def __getattribute__(self, name: str) -> Any:
        _sync_core_globals(self)
        return super().__getattribute__(name)


def _sync_core_globals(instance: Any) -> None:
    core_module = sys.modules.get("atri_qq_bot.persona.core")
    if core_module is None:
        return
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        namespace = vars(module)
        for name, value in vars(core_module).items():
            if name not in {"AtriReplyEngine"} and not name.startswith("__"):
                namespace[name] = value
