"""Read the local speech endpoint without loading a model or changing settings."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from dotenv import dotenv_values

from atri_qq_bot.runtime.paths import ENV_PATH


def validate_port(value: object) -> int:
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError("端口必须是 1–65535 的整数")
    port = int(str(value))
    if not 1 <= port <= 65535:
        raise ValueError("端口必须是 1–65535 的整数")
    return port


def local_voice_port(default: int = 8790) -> int:
    # Prefer the saved file over a desktop process's stale environment.
    values = dotenv_values(ENV_PATH, encoding="utf-8-sig")
    url = str(values.get("VOICE_SERVICE_URL") or os.getenv("VOICE_SERVICE_URL", ""))
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
            return validate_port(parsed.port if parsed.port is not None else 80)
    except ValueError:
        pass
    # A remote bot endpoint does not change which local service we manage.
    return default


def local_voice_url() -> str:
    return f"http://127.0.0.1:{local_voice_port()}"


def qq_voice_profile() -> str:
    """Follow QQ's saved voice without starting QQ or caching stale UI settings."""
    values = dotenv_values(ENV_PATH, encoding="utf-8-sig")
    return str(values.get("VOICE_PROFILE") or os.getenv("VOICE_PROFILE") or "atri").strip()
