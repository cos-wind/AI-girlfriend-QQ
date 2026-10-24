"""回复收尾守卫：自然回复不能被误判成"失败兜底文案"。

历史事故：``FAILURE_TEMPLATE_PATTERNS`` 里含 "在呢，刚忙完呢"。模型回答
"在吗" 时经常这么说，于是整条回复被 ``_finalize_reply`` 丢弃，用户侧的表现
就是"发了消息完全没反应"。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from atri_qq_bot.persona import core as persona_core
from atri_qq_bot.persona import engine_context
from atri_qq_bot.persona import reply_fallbacks, reply_rules


def _install_core_globals() -> None:
    """复刻 PersonaEngineMixin 的全局注入，让 mixin 方法可独立调用。"""

    for module in (reply_fallbacks, reply_rules, engine_context):
        for name, value in vars(persona_core).items():
            if name not in {"AtriReplyEngine"} and not name.startswith("__"):
                setattr(module, name, value)


def _finalize(reply_text: str, *, user_text: str = "在吗") -> str:
    _install_core_globals()
    return engine_context.EngineContextMixin._finalize_reply(
        SimpleNamespace(),
        "private:900000001",
        user_text,
        reply_text,
        strict_quality=False,
    )


def test_natural_short_reply_is_not_rejected() -> None:
    # 这句曾经被当成失败兜底文案，导致"在吗"完全得不到回复。
    assert _finalize("在呢，刚忙完呢") == "在呢，刚忙完呢"


def test_real_failure_templates_are_still_rejected() -> None:
    for text in ("刚才没接住，再说一遍吧", "这张图这次没有稳定识别出来"):
        with pytest.raises(RuntimeError):
            _finalize(text)


def test_failure_pattern_list_keeps_only_fallback_only_phrases() -> None:
    assert "在呢，刚忙完呢" not in persona_core.FAILURE_TEMPLATE_PATTERNS
    assert "刚才没接住，再说一遍吧" in persona_core.FAILURE_TEMPLATE_PATTERNS


def test_persona_core_module_is_the_sync_source() -> None:
    """mixin 依赖 core.py 的全局注入；这里守住注入来源不被人为改名。"""

    assert "atri_qq_bot.persona.core" in sys.modules
