"""评测与群聊总结子系统的独立配置。

这里刻意不向 :class:`BotConfig` 塞入字段：insights 是可插拔旁路，关闭后不应
改变机器人核心配置契约。所有设置均可通过 ``.env`` 覆盖。
"""

from __future__ import annotations

import os
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..runtime.paths import MODEL_PROFILE_PATH, PROJECT_ROOT


ALL_DIMENSIONS = (
    "relevancy",
    "accuracy",
    "completeness",
    "coherence",
    "faithfulness",
    "hallucination",
)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = str(os.getenv(name, "") or "").replace("，", ",")
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


def _chat_profile(profile_id: str) -> dict[str, str] | None:
    """读取模型页面已保存的聊天档案，只取评测所需的非 UI 字段。"""
    if not profile_id or not MODEL_PROFILE_PATH.exists():
        return None
    try:
        payload = json.loads(MODEL_PROFILE_PATH.read_text(encoding="utf-8-sig", errors="replace"))
        profiles = payload.get("profiles", []) if isinstance(payload, dict) else payload
        for profile in profiles if isinstance(profiles, list) else []:
            if not isinstance(profile, dict) or str(profile.get("id") or "") != profile_id:
                continue
            if str(profile.get("model_type") or "chat") != "chat":
                return None
            return {
                "base_url": str(profile.get("base_url") or "").strip().rstrip("/"),
                "model": str(profile.get("model") or "").strip(),
                "api_key": str(profile.get("api_key") or "").strip(),
            }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


@dataclass(frozen=True)
class InsightsConfig:
    """旁路服务配置；默认值偏保守，避免抢占回复链路资源。"""

    database_path: Path
    evaluation_enabled: bool
    system_evaluation_enabled: bool
    model_evaluation_enabled: bool
    dimensions: tuple[str, ...]
    judge_base_url: str
    judge_api_key: str
    judge_model: str
    judge_source: str
    judge_profile_id: str
    judge_timeout_seconds: float
    evaluation_workers: int
    evaluation_queue_size: int
    semantic_enabled: bool
    embedding_model: str
    embedding_local_only: bool
    semantic_weight: float
    group_archive_enabled: bool
    summary_enabled: bool
    summary_schedule_enabled: bool
    summary_schedule_time: str
    summary_schedule_period: str
    summary_lookback_hours: int
    summary_min_messages: int
    summary_group_ids: tuple[str, ...]
    summary_max_messages: int
    topic_cluster_threshold: float
    topic_max_clusters: int

    @classmethod
    def from_env(cls) -> "InsightsConfig":
        openai_base = str(os.getenv("OPENAI_BASE_URL", "") or "").strip()
        openai_key = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
        openai_model = str(os.getenv("OPENAI_MODEL", "") or "").strip()
        use_chat_model = _bool("EVALUATION_USE_CHAT_MODEL", True)
        profile_id = str(os.getenv("EVALUATION_MODEL_PROFILE_ID", "") or "").strip()
        selected_profile = _chat_profile(profile_id)
        deepseek_key = str(os.getenv("DEEPSEEK_API_KEY", "") or "").strip()
        legacy_key = str(os.getenv("EVALUATION_API_KEY", "") or "").strip()
        if selected_profile and selected_profile["base_url"] and selected_profile["model"]:
            judge_key = selected_profile["api_key"]
            judge_base = selected_profile["base_url"]
            judge_model = selected_profile["model"]
            judge_source = "selected_model_profile"
        elif use_chat_model:
            # 评测直接复用“模型”页面当前激活的聊天模型，避免 WebUI 出现第二套
            # 密钥和模型配置；切换模型档案后通过 reload_config 即时生效。
            judge_key = openai_key
            judge_base = openai_base or "https://api.openai.com/v1"
            judge_model = openai_model or "gpt-4.1-mini"
            judge_source = "active_chat_model"
        else:
            judge_key = legacy_key or deepseek_key
            judge_base = str(os.getenv("EVALUATION_BASE_URL", "") or "").strip()
            if not judge_base:
                judge_base = "https://api.deepseek.com/v1"
            judge_model = str(os.getenv("EVALUATION_MODEL", "deepseek-chat") or "deepseek-chat").strip()
            judge_source = "legacy_evaluation_config"

        configured_dimensions = tuple(
            value for value in _csv("EVALUATION_DIMENSIONS", ALL_DIMENSIONS)
            if value in ALL_DIMENSIONS
        )
        path_raw = str(os.getenv("INSIGHTS_DB_PATH", "data/insights/insights.sqlite3") or "").strip()
        database_path = Path(path_raw).expanduser()
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path

        schedule_time = str(os.getenv("GROUP_SUMMARY_SCHEDULE_TIME", "00:10") or "00:10").strip()
        if len(schedule_time) != 5 or schedule_time[2] != ":":
            schedule_time = "00:10"
        try:
            hour, minute = (int(value) for value in schedule_time.split(":"))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
        except ValueError:
            schedule_time = "00:10"
        schedule_period = str(os.getenv("GROUP_SUMMARY_SCHEDULE_PERIOD", "daily") or "daily").strip().lower()
        if schedule_period not in {"daily", "weekly", "monthly"}:
            schedule_period = "daily"

        return cls(
            database_path=database_path.resolve(),
            evaluation_enabled=_bool("EVALUATION_ENABLED", True),
            system_evaluation_enabled=_bool("SYSTEM_EVALUATION_ENABLED", True),
            model_evaluation_enabled=_bool("MODEL_EVALUATION_ENABLED", True),
            dimensions=configured_dimensions or ALL_DIMENSIONS,
            judge_base_url=judge_base.rstrip("/"),
            judge_api_key=judge_key,
            judge_model=judge_model,
            judge_source=judge_source,
            judge_profile_id=profile_id if selected_profile else "",
            judge_timeout_seconds=_float("EVALUATION_TIMEOUT_SECONDS", 45.0, 5.0, 180.0),
            evaluation_workers=_int("EVALUATION_WORKERS", 1, 1, 4),
            evaluation_queue_size=_int("EVALUATION_QUEUE_SIZE", 256, 16, 5000),
            semantic_enabled=_bool("EVALUATION_SEMANTIC_ENABLED", True),
            embedding_model=str(
                os.getenv(
                    "INSIGHTS_EMBEDDING_MODEL",
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                )
            ).strip(),
            embedding_local_only=_bool("INSIGHTS_EMBEDDING_LOCAL_ONLY", False),
            semantic_weight=_float("EVALUATION_SEMANTIC_WEIGHT", 0.15, 0.0, 0.5),
            group_archive_enabled=_bool("GROUP_CHAT_ARCHIVE_ENABLED", True),
            summary_enabled=_bool("GROUP_SUMMARY_ENABLED", True),
            # 旧版全局计划字段仅为兼容旧配置保留；实际调度由 SQLite 中的逐群计划驱动。
            summary_schedule_enabled=_bool("GROUP_SUMMARY_SCHEDULE_ENABLED", False),
            summary_schedule_time=schedule_time,
            summary_schedule_period=schedule_period,
            summary_lookback_hours=_int("GROUP_SUMMARY_LOOKBACK_HOURS", 24, 1, 24 * 366),
            summary_min_messages=_int("GROUP_SUMMARY_MIN_MESSAGES", 20, 1, 10000),
            summary_group_ids=_csv("GROUP_SUMMARY_GROUP_IDS", ()),
            summary_max_messages=_int("GROUP_SUMMARY_MAX_MESSAGES", 3000, 100, 20000),
            topic_cluster_threshold=_float("GROUP_SUMMARY_CLUSTER_THRESHOLD", 0.52, 0.1, 0.95),
            topic_max_clusters=_int("GROUP_SUMMARY_MAX_TOPICS", 8, 2, 20),
        )

    @property
    def judge_ready(self) -> bool:
        return bool(self.judge_api_key and self.judge_base_url and self.judge_model)

    def public_dict(self) -> dict[str, Any]:
        """返回给 WebUI 的脱敏配置。"""
        data = asdict(self)
        data["database_path"] = str(self.database_path)
        data["judge_api_key"] = ""
        data["judge_ready"] = self.judge_ready
        return data


EDITABLE_ENV_FIELDS = {
    "EVALUATION_ENABLED",
    "SYSTEM_EVALUATION_ENABLED",
    "MODEL_EVALUATION_ENABLED",
    "EVALUATION_MODEL_PROFILE_ID",
    # API Key 只允许通过显式输入写入；public_dict 永远不会回传它。
    "EVALUATION_API_KEY",
    "EVALUATION_BASE_URL",
    "EVALUATION_TIMEOUT_SECONDS",
    "EVALUATION_DIMENSIONS",
    "EVALUATION_MODEL",
    "EVALUATION_SEMANTIC_ENABLED",
    "EVALUATION_SEMANTIC_WEIGHT",
    "GROUP_CHAT_ARCHIVE_ENABLED",
    "GROUP_SUMMARY_ENABLED",
    "GROUP_SUMMARY_SCHEDULE_ENABLED",
    "GROUP_SUMMARY_SCHEDULE_TIME",
    "GROUP_SUMMARY_SCHEDULE_PERIOD",
    "GROUP_SUMMARY_LOOKBACK_HOURS",
    "GROUP_SUMMARY_MIN_MESSAGES",
    "GROUP_SUMMARY_GROUP_IDS",
}


def save_insights_env(changes: dict[str, Any]) -> None:
    """只改写 insights 白名单字段，并保留用户原有 ``.env`` 排版和注释。"""
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if env_path.exists() else []
    normalized = {
        key: ("true" if value else "false") if isinstance(value, bool) else str(value).strip()
        for key, value in changes.items()
        if key in EDITABLE_ENV_FIELDS
    }
    # WebUI 的密码框允许留空表示“保持原值”。避免用户保存其它设置时
    # 意外清空已经配置好的评测密钥；如需清除，请直接编辑 .env。
    if not normalized.get("EVALUATION_API_KEY"):
        normalized.pop("EVALUATION_API_KEY", None)
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in normalized:
            output.append(f"{key}={normalized[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in normalized.items():
        if key not in seen:
            output.append(f"{key}={value}")
    env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
