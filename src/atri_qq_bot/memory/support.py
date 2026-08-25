from __future__ import annotations

import sys
from typing import Any


class MemoryMixin:
    """Preserve memory.py as the runtime compatibility seam after splitting."""

    def __getattribute__(self, name: str) -> Any:
        _sync_memory_globals(self)
        return super().__getattribute__(name)


def _sync_memory_globals(instance: Any) -> None:
    package = sys.modules.get("atri_qq_bot.memory")
    if package is None:
        return
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        namespace = vars(module)
        for name, value in vars(package).items():
            if name != "UserMemoryStore" and not name.startswith("__"):
                namespace[name] = value
