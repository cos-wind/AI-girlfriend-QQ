from __future__ import annotations

from .rule_common import *  # noqa: F403
from . import affection_rules, extraction_rules, feature_rules, profile_rules


_RULE_MODULES = (affection_rules, feature_rules, extraction_rules, profile_rules)

for _module in _RULE_MODULES:
    for _name, _value in vars(_module).items():
        if not _name.startswith("__"):
            globals()[_name] = _value

# Functions are intentionally kept in their rule module, but they share the
# assembled rule namespace so cross-rule calls remain identical to core.py.
for _module in _RULE_MODULES:
    for _name, _value in vars().copy().items():
        if not _name.startswith("__"):
            setattr(_module, _name, _value)
