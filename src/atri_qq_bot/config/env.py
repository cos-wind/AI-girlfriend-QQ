from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_path(name: str, default: Path, base: Path) -> Path:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    path = Path(value.strip())
    if path.is_absolute():
        return path
    return base / path


def _env_int_tuple(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    value = os.getenv(name)
    if not value or not value.strip():
        return default

    numbers: list[int] = []
    for piece in value.replace("，", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        numbers.append(int(piece))
    return tuple(numbers)
