"""账号作用域的数据布局。

**默认账号沿用今天的全局路径，一个新文件都不搬**；非默认账号在
``data/accounts/qq-<号码>/`` 下拥有完全独立的数据区。这个不对称是刻意的：
它把"账号隔离"和"数据搬迁"两件风险拆开，搬迁风险直接归零。

```
data/
├── memory/users.json                  ← 默认账号，原地不动
├── memory/semantic_memory.sqlite3
├── cognition/state.sqlite3
├── insights/insights.sqlite3
├── qzone_automation.sqlite3
├── webui/*.json
└── accounts/
    ├── index.sqlite3                  ← 账号注册表
    └── qq-10002/                 ← 非默认账号的独立数据区
        ├── memory/users.json
        ├── memory/backups/
        ├── memory/semantic_memory.sqlite3
        ├── cognition/state.sqlite3
        ├── insights/insights.sqlite3
        ├── qzone_automation.sqlite3
        ├── webui/*.json
        └── prompts/                   ← 阶段 4：只放差异文件，缺的回落 docs/prompts/
```

为什么用目录隔离而不是"单库 + account_id 列"：后者要求把 12.8MB 的记忆 JSON 与
61MB 的评测库全量导入，而且每一条 SQL 漏写 ``WHERE account_id=?`` 就会静默串号。
目录隔离下串号在物理上不可能发生，回退也只是删目录。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.env import _env_path, _project_root
from ..runtime import paths as runtime_paths
from .registry import Account


@dataclass(frozen=True)
class AccountPaths:
    """一个账号的数据位置。``root`` 为 ``None`` 表示沿用全局路径（默认账号）。"""

    account_id: str
    is_default: bool
    root: Path | None
    bot_qq: int
    memory_path: Path
    memory_backup_dir: Path
    memory_retrieval_path: Path
    cognition_state_path: Path
    insights_db_path: Path
    qzone_db_path: Path
    webui_dir: Path
    prompt_dir: Path
    sticker_capture_dir: Path

    def public_dict(self) -> dict[str, Any]:
        """给 WebUI 展示用；``data/`` 内显示相对路径，更易读。"""
        root = _project_root()

        def show(path: Path) -> str:
            # 统一用正斜杠：WebUI 拿到的路径格式不应该因为"在不在项目目录下"
            # 而在 posix 与 Windows 反斜杠之间跳变。
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                return path.as_posix()

        return {
            "account_id": self.account_id,
            "is_default": self.is_default,
            "root": show(self.root) if self.root else None,
            "bot_qq": self.bot_qq,
            "memory_path": show(self.memory_path),
            "memory_backup_dir": show(self.memory_backup_dir),
            "memory_retrieval_path": show(self.memory_retrieval_path),
            "cognition_state_path": show(self.cognition_state_path),
            "insights_db_path": show(self.insights_db_path),
            "qzone_db_path": show(self.qzone_db_path),
            "webui_dir": show(self.webui_dir),
            "prompt_dir": show(self.prompt_dir),
            "sticker_capture_dir": show(self.sticker_capture_dir),
        }


def accounts_root(config: Any) -> Path:
    """``data/accounts/`` —— 注册表所在目录，也是各账号数据区的父目录。"""
    return Path(getattr(config, "accounts_db_path")).expanduser().parent


def account_dir_name(account: Account) -> str:
    return f"qq-{account.qq}"


def _default_paths(config: Any) -> AccountPaths:
    """默认账号：逐项复刻今天的全局路径，确保零搬迁。

    注意 ``qzone_db_path``：``atri_webui/server.py:276`` 今天用
    ``Path(os.getenv("QZONE_AUTOMATION_DB", "data/qzone_automation.sqlite3"))``，
    这是**相对当前工作目录**的路径（不是相对 PROJECT_ROOT）。这里刻意原样复刻，
    避免账号化顺手改变既有行为。
    """
    root = _project_root()
    insights_db_path = _env_path(
        "INSIGHTS_DB_PATH", root / "data" / "insights" / "insights.sqlite3", root
    ).resolve()
    return AccountPaths(
        account_id="__legacy__",
        is_default=True,
        root=None,
        bot_qq=int(getattr(config, "bot_qq", 0) or 0),
        memory_path=Path(getattr(config, "memory_path")),
        memory_backup_dir=runtime_paths.MEMORY_BACKUP_DIR,
        memory_retrieval_path=Path(getattr(config, "memory_retrieval_path")),
        cognition_state_path=Path(getattr(config, "cognition_state_path")),
        insights_db_path=insights_db_path,
        qzone_db_path=Path(
            os.getenv("QZONE_AUTOMATION_DB", "data/qzone_automation.sqlite3")
        ),
        webui_dir=runtime_paths.WEBUI_DIR,
        prompt_dir=runtime_paths.PROMPT_DIR,
        sticker_capture_dir=Path(getattr(config, "sticker_capture_dir")),
    )


def _scoped_paths(config: Any, account: Account) -> AccountPaths:
    """非默认账号：所有数据落在自己的目录里。"""
    root = accounts_root(config) / account_dir_name(account)
    return AccountPaths(
        account_id=account.account_id,
        is_default=False,
        root=root,
        bot_qq=account.qq_int,
        memory_path=root / "memory" / "users.json",
        memory_backup_dir=root / "memory" / "backups",
        memory_retrieval_path=root / "memory" / "semantic_memory.sqlite3",
        cognition_state_path=root / "cognition" / "state.sqlite3",
        insights_db_path=root / "insights" / "insights.sqlite3",
        qzone_db_path=root / "qzone_automation.sqlite3",
        webui_dir=root / "webui",
        prompt_dir=root / "prompts",
        sticker_capture_dir=root / "stickers_capture",
    )


def account_data_paths(config: Any, account: Account | None) -> AccountPaths | None:
    """解析账号的数据位置；``account`` 为 ``None`` 时返回 ``None``。

    不创建任何目录——需要目录时用 :func:`ensure_account_layout`。
    """
    if account is None:
        return None
    if account.is_default:
        return _default_paths(config)
    return _scoped_paths(config, account)


def ensure_account_layout(
    config: Any, account: Account | None
) -> AccountPaths | None:
    """确保账号的数据目录存在，返回其路径布局。

    只给非默认账号建目录：默认账号沿用全局路径，那些目录本来就在。
    """
    layout = account_data_paths(config, account)
    if layout is None:
        return None
    if layout.root is None:
        return layout
    for directory in (
        layout.root,
        layout.memory_path.parent,
        layout.memory_backup_dir,
        layout.memory_retrieval_path.parent,
        layout.cognition_state_path.parent,
        layout.insights_db_path.parent,
        layout.qzone_db_path.parent,
        layout.webui_dir,
        layout.prompt_dir,
        layout.sticker_capture_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return layout


__all__ = [
    "AccountPaths",
    "account_data_paths",
    "account_dir_name",
    "accounts_root",
    "ensure_account_layout",
]
