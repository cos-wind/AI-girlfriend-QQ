"""Compatibility alias for the shared implementation (one module state)."""

import sys

from atri_shared import service_control as _implementation

sys.modules[__name__] = _implementation
