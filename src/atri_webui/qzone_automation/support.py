from __future__ import annotations

import sys
from typing import Any


class QZoneMixin:
    def __getattribute__(self, name: str) -> Any:
        _sync_qzone_globals(self)
        return super().__getattribute__(name)


def _sync_qzone_globals(instance: Any) -> None:
    package = sys.modules.get("atri_webui.qzone_automation")
    if package is None:
        return
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        for name, value in vars(package).items():
            if name not in {"QZoneAutomation", "QZoneAutomationStore"} and not name.startswith("__"):
                vars(module)[name] = value
