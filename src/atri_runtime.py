"""Qbot source paths and optional isolated user state; no desktop dependency."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

VERSION = "0.5.0"


def resource_root() -> Path:
    return Path(__file__).resolve().parents[1]


def user_root() -> Path:
    configured = os.environ.get("ATRI_QBOT_USER_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else resource_root()


def instance_suffix() -> str:
    if os.environ.get("ATRI_QBOT_USER_DIR"):
        return "-" + hashlib.sha256(str(user_root()).casefold().encode()).hexdigest()[:12]
    return ""
