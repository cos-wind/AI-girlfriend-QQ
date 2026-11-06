"""Source-checkout compatibility for the relocated MaiBot QQ Zone plugin.

Wheels map this package directly to plugins/maibot/qqzone in pyproject.toml.
Keep one implementation while preserving existing atri_qq_bot.qzone imports.
"""
from pathlib import Path

_source = Path(__file__).resolve().parents[3] / "plugins/maibot/qqzone"
if _source.is_dir():
    __path__ = [str(_source)]
