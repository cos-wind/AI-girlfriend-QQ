"""Shared daily project logging; imports never configure handlers."""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from logging import Handler, LogRecord
from pathlib import Path
from typing import Any
from .paths import LOG_DIR


class DailyProjectFileHandler(Handler):
    """按本地日期写入 ``dev/workspace/logs/project-YYYY-MM-DD.log`` 的轻量 Handler。"""

    def __init__(self, directory: Path, retention_days: int = 14) -> None:
        super().__init__()
        self._directory = directory
        self._retention_days = retention_days
        self._date = ""
        self._stream: Any | None = None

    def emit(self, record: LogRecord) -> None:
        try:
            date = datetime.now().astimezone().date().isoformat()
            if date != self._date:
                self._open_for(date)
            if self._stream is not None:
                self._stream.write(self.format(record) + "\n")
                self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()

    def _open_for(self, date: str) -> None:
        if self._stream is not None:
            self._stream.close()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._stream = (self._directory / f"project-{date}.log").open(
            "a", encoding="utf-8"
        )
        self._date = date
        cutoff = datetime.now().astimezone().timestamp() - self._retention_days * 86400
        for path in self._directory.glob("project-????-??-??.log"):
            if path.stat().st_mtime < cutoff:
                with __import__("contextlib").suppress(OSError):
                    path.unlink()


def configure_project_logging(level: str | None = None) -> logging.Logger:
    """初始化一次 ATRI 根日志器；重复调用不会产生重复输出。"""

    logger = logging.getLogger("atri")
    if getattr(logger, "_atri_configured", False):
        return logger
    selected = str(level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logger.setLevel(getattr(logging, selected, logging.INFO))
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = DailyProjectFileHandler(LOG_DIR)
    file_handler.setFormatter(formatter)
    # 桌宠会通过 pythonw.exe 隐藏启动服务。后台进程不创建/绑定控制台，
    # 仅保留文件日志；只有开发者从真实终端手动运行时才额外输出到控制台。
    # 这样既不牺牲调试能力，也不会因日志输出让 Windows 闪出黑色终端。
    if sys.stdout is not None and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        logger.addHandler(console)
    logger.addHandler(file_handler)
    logger._atri_configured = True  # type: ignore[attr-defined]
    logger.info("日志系统已就绪：级别=%s，文件=%s", logger.level, LOG_DIR)
    return logger


def read_project_logs(level: str = "all", limit: int = 240) -> list[str]:
    """读取当天统一日志的末尾，供本机 WebUI 轮询展示。"""

    date = datetime.now().astimezone().date().isoformat()
    path = LOG_DIR / f"project-{date}.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    accepted = {"DEBUG", "INFO", "WARNING", "ERROR"}
    selected = str(level or "all").upper()
    if selected in accepted:
        lines = [line for line in lines if f" {selected:<5} " in line]
    return lines[-max(20, min(int(limit or 240), 1000)):]


