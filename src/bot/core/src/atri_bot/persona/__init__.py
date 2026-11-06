from __future__ import annotations

from . import core as _core


for _name in dir(_core):
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = getattr(_core, _name)
del _name

__all__ = [
    _name
    for _name in globals()
    if not (_name.startswith("__") and _name.endswith("__")) and _name != "_core"
]
