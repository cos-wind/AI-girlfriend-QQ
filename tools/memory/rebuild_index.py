"""从现有 JSON 事实源重建 SQLite 检索索引。

只读 users.json，不调用聊天模型、不生成新记忆；适合项目运行时执行。写入
采用短 SQLite 事务，失败不会修改 JSON。默认必须显式传 --all，避免误触发全量任务。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from atri_qq_bot.config import load_config  # noqa: E402
from atri_qq_bot.retrieval import ContextRetrievalPlanner, RetrievalSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 ATRI SQLite 记忆检索索引")
    parser.add_argument("--all", action="store_true", help="确认重建全部 JSON 会话索引")
    args = parser.parse_args()
    if not args.all:
        print("未执行：请明确传入 --all。")
        return 2

    config = load_config()
    if not config.memory_path.exists():
        print(f"未执行：找不到记忆文件 {config.memory_path}")
        return 1
    data = json.loads(config.memory_path.read_text(encoding="utf-8-sig", errors="replace"))
    conversations = data.get("conversations") if isinstance(data, dict) else {}
    if not isinstance(conversations, dict):
        print("未执行：记忆文件的 conversations 不是对象。")
        return 1

    planner = ContextRetrievalPlanner(RetrievalSettings.from_config(config.memory_path, config))
    total = 0
    for index, (scope, profile) in enumerate(conversations.items(), start=1):
        if not isinstance(profile, dict):
            continue
        planner._sync_profile(str(scope), profile)  # 维护脚本使用同一同步规则，避免两套格式。
        total += 1
        if index % 25 == 0:
            print(f"已同步 {index}/{len(conversations)} 个会话")
    planner._ensure_lore_index()
    print(f"完成：同步 {total} 个会话，索引状态：{planner.status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
