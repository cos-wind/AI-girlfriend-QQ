from __future__ import annotations

import sys
from typing import Any


class ToolboxMixin:
    """Keep the package-level compatibility seam visible to split implementations."""

    def __getattribute__(self, name: str) -> Any:
        _sync_toolbox_globals(self)
        return super().__getattribute__(name)


def _sync_toolbox_globals(instance: Any) -> None:
    package = sys.modules.get("atri_qq_bot.toolbox")
    if package is None:
        return
    helper = sys.modules.get("atri_qq_bot.toolbox.helpers")
    if helper is not None:
        _copy_package_globals(package, helper)
    for cls in type(instance).__mro__:
        module = sys.modules.get(cls.__module__)
        if module is None or module is sys.modules[__name__]:
            continue
        _copy_package_globals(package, module)


def _copy_package_globals(package: Any, module: Any) -> None:
    namespace = vars(module)
    for name, value in vars(package).items():
        if name != "ToolAnalyzer" and not name.startswith("__"):
            namespace[name] = value
