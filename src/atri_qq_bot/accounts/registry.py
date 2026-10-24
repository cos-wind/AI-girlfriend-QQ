"""机器人账号注册表。

以 SQLite 保存"亚托莉可以登录哪些 QQ 账号"这一事实，是账号管理系统的唯一
身份来源：WebUI 用户中心、评测库分账号、人设与配置分层都从这里取身份。

设计约定（与项目既有代码保持一致）：

* 用 stdlib ``sqlite3``，``PRAGMA journal_mode=WAL`` + ``busy_timeout``，
  ``CREATE TABLE IF NOT EXISTS`` 建表，``PRAGMA user_version`` 记录 schema 版本。
  不引入 ORM 或迁移框架。
* ``account_id`` 是稳定主键，格式 ``qq:<号码>``；``qq`` 列另外保留裸号码，
  便于与 NapCat 的 ``get_login_info`` 返回值直接比对。
* 新发现的账号默认 ``enabled=0``、``confirmed=0``。在用户于 WebUI 确认之前，
  它的行为与今天"账号不一致"完全一致（忽略全部消息 + 告警），所以开启账号系统
  本身不会凭空改变任何一个新账号的行为。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Mapping

# 当前 schema 版本。
# v1：accounts
# v2：account_settings（账号级配置覆盖）
# 加表只需往 _SCHEMA_STATEMENTS 里加一条 CREATE TABLE IF NOT EXISTS——
# _ensure_schema 每次构造都会把所有语句跑一遍，所以新表对已有库也自动生效。
# user_version 只是记账，让"这个库经历过哪些版本"可查。
SCHEMA_VERSION = 2

PLATFORM_QQ = "qq"


def account_id_for(qq: int | str) -> str:
    """把 QQ 号规范成稳定的账号主键。"""
    value = str(qq if qq is not None else "").strip()
    if not value.isdigit():
        raise ValueError(f"QQ 号必须是纯数字：{qq!r}")
    return f"{PLATFORM_QQ}:{value}"


def qq_from_account_id(account_id: str) -> str:
    """从账号主键取回裸 QQ 号。"""
    value = str(account_id or "").strip()
    prefix = f"{PLATFORM_QQ}:"
    if not value.startswith(prefix) or not value[len(prefix) :].isdigit():
        raise ValueError(f"账号 ID 格式非法：{account_id!r}")
    return value[len(prefix) :]


@dataclass(frozen=True)
class Account:
    """一个亚托莉可以登录的机器人账号。"""

    account_id: str
    platform: str
    qq: str
    display_name: str
    persona_id: str | None
    is_default: bool
    enabled: bool
    confirmed: bool
    created_at: float
    updated_at: float
    last_login_at: float | None
    last_seen_at: float | None
    notes: str

    @property
    def qq_int(self) -> int:
        return int(self.qq)

    def public_dict(self) -> dict[str, Any]:
        """给 WebUI 用的序列化形式。"""
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "qq": self.qq,
            "display_name": self.display_name,
            "persona_id": self.persona_id,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "confirmed": self.confirmed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
            "last_seen_at": self.last_seen_at,
            "notes": self.notes,
        }


_COLUMNS = (
    "account_id",
    "platform",
    "qq",
    "display_name",
    "persona_id",
    "is_default",
    "enabled",
    "confirmed",
    "created_at",
    "updated_at",
    "last_login_at",
    "last_seen_at",
    "notes",
)

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS accounts (
      account_id    TEXT PRIMARY KEY,
      platform      TEXT NOT NULL DEFAULT 'qq',
      qq            TEXT NOT NULL UNIQUE,
      display_name  TEXT NOT NULL DEFAULT '',
      persona_id    TEXT,
      is_default    INTEGER NOT NULL DEFAULT 0,
      enabled       INTEGER NOT NULL DEFAULT 1,
      confirmed     INTEGER NOT NULL DEFAULT 0,
      created_at    REAL NOT NULL,
      updated_at    REAL NOT NULL,
      last_login_at REAL,
      last_seen_at  REAL,
      notes         TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_accounts_is_default ON accounts(is_default)",
    "CREATE INDEX IF NOT EXISTS idx_accounts_enabled ON accounts(enabled)",
    # 账号级配置覆盖。只存"和全局默认不同的项"——键名与 .env / CONFIG_FIELDS
    # 同名，值以 JSON 保存以便保留类型（bool / int / float / str）。
    # 没有行 = 继承全局默认，这正是"恢复继承"的实现方式。
    """
    CREATE TABLE IF NOT EXISTS account_settings (
      account_id TEXT NOT NULL,
      key        TEXT NOT NULL,
      value_json TEXT NOT NULL,
      updated_at REAL NOT NULL,
      PRIMARY KEY (account_id, key)
    )
    """,
)


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=str(row["account_id"]),
        platform=str(row["platform"]),
        qq=str(row["qq"]),
        display_name=str(row["display_name"] or ""),
        persona_id=(str(row["persona_id"]) if row["persona_id"] else None),
        is_default=bool(row["is_default"]),
        enabled=bool(row["enabled"]),
        confirmed=bool(row["confirmed"]),
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
        last_login_at=(
            float(row["last_login_at"]) if row["last_login_at"] is not None else None
        ),
        last_seen_at=(
            float(row["last_seen_at"]) if row["last_seen_at"] is not None else None
        ),
        notes=str(row["notes"] or ""),
    )


class AccountRegistry:
    """账号注册表。

    构造时会建库建表（幂等）。**调用方必须先判断 ``config.account_system_enabled``**——
    账号系统关闭时不应该创建 ``data/accounts/`` 下的任何文件。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._ensure_schema()

    # ---- 基础设施 -------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=8.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=8000")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current < SCHEMA_VERSION:
                self._migrate(connection, current)

    def _migrate(self, connection: sqlite3.Connection, current: int) -> None:
        """按版本号顺序补齐 schema。

        v1 是初始版本，建表语句已经覆盖；这里仍然显式设置 user_version，
        让后续加表/加列有明确的挂载点。
        """
        del current
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # ---- 读 -------------------------------------------------------------

    def get(self, account_id: str) -> Account | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE account_id=?", (str(account_id),)
            ).fetchone()
        return _row_to_account(row) if row else None

    def get_by_qq(self, qq: int | str) -> Account | None:
        value = str(qq if qq is not None else "").strip()
        if not value:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE qq=?", (value,)
            ).fetchone()
        return _row_to_account(row) if row else None

    def list_all(self) -> list[Account]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM accounts ORDER BY is_default DESC, created_at ASC"
            ).fetchall()
        return [_row_to_account(row) for row in rows]

    def default_account(self) -> Account | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE is_default=1 ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        return _row_to_account(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])

    # ---- 写 -------------------------------------------------------------

    def register(
        self,
        qq: int | str,
        *,
        display_name: str = "",
        is_default: bool = False,
        enabled: bool = True,
        confirmed: bool = False,
        persona_id: str | None = None,
        notes: str = "",
        now: float | None = None,
    ) -> Account:
        """登记一个账号；已存在则原样返回（不覆盖人工改过的字段）。"""
        account_id = account_id_for(qq)
        existing = self.get(account_id)
        if existing is not None:
            return existing

        stamp = float(now if now is not None else time.time())
        raw_qq = qq_from_account_id(account_id)
        with self._connect() as connection:
            if is_default:
                connection.execute("UPDATE accounts SET is_default=0")
            connection.execute(
                "INSERT INTO accounts("
                + ",".join(_COLUMNS)
                + ") VALUES ("
                + ",".join("?" for _ in _COLUMNS)
                + ")",
                (
                    account_id,
                    PLATFORM_QQ,
                    raw_qq,
                    str(display_name or ""),
                    persona_id,
                    1 if is_default else 0,
                    1 if enabled else 0,
                    1 if confirmed else 0,
                    stamp,
                    stamp,
                    None,
                    None,
                    str(notes or ""),
                ),
            )
        created = self.get(account_id)
        if created is None:  # pragma: no cover - 插入后必然可读
            raise RuntimeError(f"账号写入后读取失败：{account_id}")
        return created

    def update(self, account_id: str, **fields: Any) -> Account | None:
        """更新白名单字段；返回更新后的账号（不存在则 None）。"""
        allowed = {
            "display_name",
            "persona_id",
            "is_default",
            "enabled",
            "confirmed",
            "notes",
            "last_login_at",
            "last_seen_at",
        }
        changes = {key: value for key, value in fields.items() if key in allowed}
        if not changes:
            return self.get(account_id)

        assignments: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            assignments.append(f"{key}=?")
            if isinstance(value, bool):
                values.append(1 if value else 0)
            else:
                values.append(value)
        assignments.append("updated_at=?")
        values.append(float(fields.get("now") or time.time()))

        with self._connect() as connection:
            if changes.get("is_default"):
                connection.execute("UPDATE accounts SET is_default=0")
            connection.execute(
                f"UPDATE accounts SET {', '.join(assignments)} WHERE account_id=?",
                (*values, str(account_id)),
            )
        return self.get(account_id)

    def set_default(self, account_id: str) -> Account | None:
        return self.update(account_id, is_default=True)

    def mark_confirmed(self, account_id: str, *, enabled: bool = True) -> Account | None:
        return self.update(account_id, confirmed=True, enabled=enabled)

    def record_login(self, account_id: str, *, at: float | None = None) -> Account | None:
        stamp = float(at if at is not None else time.time())
        return self.update(account_id, last_login_at=stamp, now=stamp)

    def record_seen(self, account_id: str, *, at: float | None = None) -> Account | None:
        stamp = float(at if at is not None else time.time())
        return self.update(account_id, last_seen_at=stamp, now=stamp)

    def observe_from_napcat(
        self,
        qq: int | str,
        *,
        display_name: str = "",
        now: float | None = None,
    ) -> tuple[Account, bool]:
        """记录"NapCat 现在登录的是这个号"，返回 (账号, 是否是首次发现)。

        首次发现一律以 ``enabled=0``、``confirmed=0`` 登记：在用户确认之前，
        这个账号不会获得任何数据区，行为等同今天的"账号不一致"。
        """
        account_id = account_id_for(qq)
        existing = self.get(account_id)
        if existing is not None:
            updated = self.record_login(account_id, at=now)
            return (updated or existing), False

        created = self.register(
            qq,
            display_name=display_name,
            is_default=False,
            enabled=False,
            confirmed=False,
            notes="由 NapCat 登录状态自动发现，等待人工确认",
            now=now,
        )
        created = self.record_login(account_id, at=now) or created
        return created, True

    # ---- 账号级配置覆盖 ------------------------------------------------

    def settings(self, account_id: str) -> dict[str, Any]:
        """该账号的配置覆盖（已解析为原始类型）。没有行 = 全部继承全局默认。"""
        rows = self.setting_rows(account_id)
        return {row["key"]: row["value"] for row in rows}

    def setting_rows(self, account_id: str) -> list[dict[str, Any]]:
        """带元信息的形式，供 WebUI 展示"已覆盖 / 更新时间"。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value_json, updated_at FROM account_settings "
                "WHERE account_id=? ORDER BY key",
                (str(account_id),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["value_json"])
            except (TypeError, ValueError):
                # 坏数据不能让整个面板读不出来；原样返回字符串。
                value = row["value_json"]
            result.append(
                {
                    "key": str(row["key"]),
                    "value": value,
                    "updated_at": float(row["updated_at"] or 0.0),
                }
            )
        return result

    def set_setting(
        self, account_id: str, key: str, value: Any, *, now: float | None = None
    ) -> None:
        self.set_settings(account_id, {key: value}, now=now)

    def set_settings(
        self,
        account_id: str,
        values: Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        if not values:
            return
        stamp = float(now if now is not None else time.time())
        with self._connect() as connection:
            for key, value in values.items():
                connection.execute(
                    "INSERT INTO account_settings(account_id,key,value_json,updated_at) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(account_id,key) DO UPDATE SET "
                    "value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (
                        str(account_id),
                        str(key),
                        json.dumps(value, ensure_ascii=False),
                        stamp,
                    ),
                )

    def delete_setting(self, account_id: str, key: str) -> bool:
        """删掉一项覆盖 = 恢复继承全局默认。返回是否真的删掉了。"""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM account_settings WHERE account_id=? AND key=?",
                (str(account_id), str(key)),
            )
        return bool(cursor.rowcount)

    def clear_settings(self, account_id: str) -> int:
        """清空该账号的全部覆盖（"全部恢复继承"），返回删除行数。"""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM account_settings WHERE account_id=?",
                (str(account_id),),
            )
        return int(cursor.rowcount or 0)

    def settings_count(self, account_id: str) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM account_settings WHERE account_id=?",
                    (str(account_id),),
                ).fetchone()[0]
            )


def bootstrap_from_config(config: Any) -> Account | None:
    """用 ``BOT_QQ`` 引导出默认账号（只在注册表为空时生效）。

    ``BOT_QQ`` 在账号系统里语义降级为"引导用的默认账号 + 未开启跟随时的
    一致性校验值"。引导出来的账号直接标记为已确认——它本来就是用户一直在用的号。
    """
    bot_qq = int(getattr(config, "bot_qq", 0) or 0)
    if bot_qq <= 0:
        return None

    registry = AccountRegistry(getattr(config, "accounts_db_path"))
    existing = registry.get_by_qq(bot_qq)
    if existing is not None:
        return existing
    if registry.count() > 0:
        # 注册表里已经有别的账号，不要再拿 BOT_QQ 去抢默认位。
        return registry.default_account()
    return registry.register(
        bot_qq,
        display_name="亚托莉",
        is_default=True,
        enabled=True,
        confirmed=True,
        notes="由 .env 的 BOT_QQ 引导",
    )


def registry_for_config(config: Any) -> AccountRegistry:
    """按配置打开注册表。调用方必须先确认账号系统已启用。"""
    return AccountRegistry(getattr(config, "accounts_db_path"))


__all__ = [
    "Account",
    "AccountRegistry",
    "PLATFORM_QQ",
    "SCHEMA_VERSION",
    "account_id_for",
    "bootstrap_from_config",
    "qq_from_account_id",
    "registry_for_config",
]
