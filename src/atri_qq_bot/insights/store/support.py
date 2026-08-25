from __future__ import annotations

import sys
from typing import Any


class InsightsStoreMixin:
    def __getattribute__(self, name: str) -> Any:
        _sync_store_globals(self)
        return super().__getattribute__(name)


def _sync_store_globals(instance: Any) -> None:
    package = sys.modules.get("atri_qq_bot.insights.store")
    if package is None:
        return
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        for name, value in vars(package).items():
            if name != "InsightsStore" and not name.startswith("__"):
                vars(module)[name] = value
