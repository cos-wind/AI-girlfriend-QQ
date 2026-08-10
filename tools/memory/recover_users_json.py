"""合并恢复被异常缩小的 users.json。

只在确认当前文件明显小于历史完整备份时手动运行：
    python tools/memory/recover_users_json.py --source <完整备份.json>

脚本会先保留当前文件副本，再以备份为基线合并当前文件中的新会话、消息和画像，
使用临时文件原子替换，避免恢复过程中再次留下半个 JSON 文件。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("conversations"), dict):
        raise ValueError(f"不是有效的记忆文件: {path}")
    return data


def _entry_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(entry.get("layer") or ""),
        str(entry.get("category") or ""),
        str(entry.get("key") or ""),
        str(entry.get("value") or entry.get("text") or ""),
    )


def _merge_entries(old: list[Any], new: list[Any]) -> list[Any]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in [*old, *new]:
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        key = _entry_key(item)
        previous = merged.get(key)
        if previous is None or float(item.get("updated_at") or item.get("at") or 0) >= float(
            previous.get("updated_at") or previous.get("at") or 0
        ):
            merged[key] = item
    return list(merged.values())


def _merge_history(old: list[Any], new: list[Any]) -> list[Any]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in [*old, *new]:
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        key = (
            str(item.get("role") or ""),
            str(item.get("text") or ""),
            str(item.get("at") or ""),
            str(item.get("actor_id") or ""),
        )
        merged[key] = item
    return sorted(merged.values(), key=lambda item: float(item.get("at") or 0))[-300:]


def _merge_structured(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(old)
    for key, value in new.items():
        if key in {"l1", "l2", "l3", "candidates"}:
            continue
        merged[key] = copy.deepcopy(value)
    for key in ("l1", "l2", "l3", "candidates"):
        merged[key] = _merge_entries(
            list(old.get(key) or []) if isinstance(old.get(key), list) else [],
            list(new.get(key) or []) if isinstance(new.get(key), list) else [],
        )
    return merged


def _merge_conversation(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(old)
    for key, value in new.items():
        if key not in {"history", "structured_memory"}:
            merged[key] = copy.deepcopy(value)
    merged["history"] = _merge_history(
        list(old.get("history") or []) if isinstance(old.get("history"), list) else [],
        list(new.get("history") or []) if isinstance(new.get("history"), list) else [],
    )
    merged["structured_memory"] = _merge_structured(
        old.get("structured_memory") if isinstance(old.get("structured_memory"), dict) else {},
        new.get("structured_memory") if isinstance(new.get("structured_memory"), dict) else {},
    )
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, default=Path("data/memory/users.json"))
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    current = _read(args.current)
    source = _read(args.source)
    current_count = len(current["conversations"])
    source_count = len(source["conversations"])
    if source_count <= current_count:
        raise SystemExit(f"源备份并不更完整，拒绝覆盖: source={source_count}, current={current_count}")

    result = copy.deepcopy(source)
    for conversation_id, item in current["conversations"].items():
        if not isinstance(item, dict):
            continue
        old = result["conversations"].get(conversation_id, {})
        result["conversations"][conversation_id] = _merge_conversation(
            old if isinstance(old, dict) else {}, item
        )
    result["version"] = max(int(result.get("version", 1) or 1), int(current.get("version", 1) or 1))

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = args.current.with_name(f"{args.current.stem}.pre-recovery-{timestamp}.json")
    shutil.copy2(args.current, backup_path)
    temp_path = args.current.with_suffix(args.current.suffix + ".recovery.tmp")
    temp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, args.current)
    print(
        json.dumps(
            {
                "current_before": current_count,
                "source": source_count,
                "merged": len(result["conversations"]),
                "safety_backup": str(backup_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
