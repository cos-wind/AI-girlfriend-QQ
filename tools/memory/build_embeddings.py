"""低负载地为现有 SQLite 索引补建 bge-m3 向量。

这是显式维护命令，不会被 QQ 消息触发。它按条限速，并在可用内存低于 5 GiB
时拒绝启动，防止与视觉模型、游戏或语音服务抢占资源。

示例：.venv\\Scripts\\python.exe tools\\memory\\build_embeddings.py --limit 20
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from atri_qq_bot.config import load_config  # noqa: E402
from atri_qq_bot.retrieval.embeddings import OllamaEmbeddingClient  # noqa: E402
from atri_qq_bot.retrieval.repository import SemanticMemoryRepository  # noqa: E402


def free_memory_bytes() -> int:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    state = MemoryStatus()
    state.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        return 0
    return int(state.ullAvailPhys)


def main() -> int:
    parser = argparse.ArgumentParser(description="为 ATRI SQLite 记忆索引补建 bge-m3 向量")
    parser.add_argument("--limit", type=int, default=20, help="本次最多处理条数（默认 20）")
    parser.add_argument("--pause", type=float, default=0.8, help="每条之间的停顿秒数")
    args = parser.parse_args()
    available = free_memory_bytes()
    if available < 5 * 1024**3:
        print(f"已拒绝：当前可用内存仅 {available / 1024**3:.2f} GiB，低于 5 GiB 安全阈值。")
        return 2

    config = load_config()
    repo = SemanticMemoryRepository(config.memory_retrieval_path)
    client = OllamaEmbeddingClient(
        config.memory_embedding_model,
        config.memory_embedding_base_url,
        max(5.0, config.memory_embedding_timeout_seconds),
    )
    candidates = repo.embedding_candidates(config.memory_embedding_model, args.limit)
    if not candidates:
        print("没有需要补建向量的索引条目。")
        return 0
    for index, (entry_id, text) in enumerate(candidates, start=1):
        if free_memory_bytes() < 5 * 1024**3:
            print("处理中检测到可用内存不足，已安全停止。")
            return 2
        repo.save_embedding(entry_id, config.memory_embedding_model, client.embed(text))
        print(f"[{index}/{len(candidates)}] 已写入向量：{entry_id[:10]}")
        time.sleep(max(0.2, args.pause))
    print(f"完成。本模型已有 {repo.embedding_count(config.memory_embedding_model)} 条向量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
