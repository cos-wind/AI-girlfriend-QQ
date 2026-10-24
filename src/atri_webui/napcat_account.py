"""Compatibility alias: desktop and WebUI share one NapCat implementation."""
import sys
from atri_shared import napcat_account as _implementation
sys.modules[__name__] = _implementation
