"""统一的外部提示词加载器。

提示词属于可独立迭代的领域文档，不应和消息调度、工具执行或记忆算法
混在 Python 代码里。此模块只负责从 ``docs/prompts`` 读取静态文本，并
为运行时模板替换明确的 ``{{name}}`` 占位符。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .runtime.paths import PROJECT_ROOT


PROMPT_DIR = PROJECT_ROOT / "docs" / "prompts"


class PromptLoadError(RuntimeError):
    """提示词文档缺失或无法读取时抛出的明确错误。"""


@lru_cache(maxsize=64)
def _read_prompt(path: str, modified_ns: int) -> str:
    del modified_ns  # 通过缓存键感知文件变化，函数本身只负责读取。
    try:
        return Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    except OSError as exc:
        raise PromptLoadError(f"无法读取提示词文档：{path}") from exc


def load_prompt(name: str) -> str:
    """读取 ``docs/prompts/<name>.md``，并在缺失时给出可定位错误。"""

    filename = str(name).strip()
    if not filename or Path(filename).name != filename:
        raise PromptLoadError(f"非法提示词名称：{name!r}")
    path = (PROMPT_DIR / f"{filename}.md").resolve()
    try:
        path.relative_to(PROMPT_DIR.resolve())
        modified_ns = path.stat().st_mtime_ns
    except OSError as exc:
        raise PromptLoadError(f"提示词文档不存在：{path}") from exc
    return _read_prompt(str(path), modified_ns)


def render_prompt(name: str, **values: Any) -> str:
    """替换文档中的 ``{{key}}`` 占位符，不解释或执行模板代码。"""

    prompt = load_prompt(name)
    for key, value in values.items():
        prompt = prompt.replace("{{" + str(key) + "}}", str(value))
    return prompt


def clear_prompt_cache() -> None:
    """测试或 WebUI 热更新时清理已缓存的提示词。"""

    _read_prompt.cache_clear()


__all__ = ["PROMPT_DIR", "PromptLoadError", "clear_prompt_cache", "load_prompt", "render_prompt"]

