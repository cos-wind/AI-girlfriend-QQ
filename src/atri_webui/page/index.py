from __future__ import annotations

from html import escape

from .document_head import PART as DOCUMENT_HEAD
from .body_shell import PART as BODY_SHELL
from .body_model import PART as BODY_MODEL
from .body_users import PART as BODY_USERS
from .body_evaluation import PART as BODY_EVALUATION
from .body_advanced import PART as BODY_ADVANCED
from .body_qq_music import PART as BODY_QQ_MUSIC
from .body_tail import PART as BODY_TAIL
from .script_core import PART as SCRIPT_CORE
from .script_account import PART as SCRIPT_ACCOUNT
from .script_evaluation import PART as SCRIPT_EVALUATION
from .script_summary import PART as SCRIPT_SUMMARY
from .script_qq_music import PART as SCRIPT_QQ_MUSIC
from .script_status import PART as SCRIPT_STATUS
from .script_models import PART as SCRIPT_MODELS
from .script_proactive import PART as SCRIPT_PROACTIVE
from .script_directory import PART as SCRIPT_DIRECTORY
from .script_qzone import PART as SCRIPT_QZONE
from .script_services import PART as SCRIPT_SERVICES
from .script_strategy import PART as SCRIPT_STRATEGY
from .script_memory import PART as SCRIPT_MEMORY
from .script_voice_test import PART as SCRIPT_VOICE_TEST
from ..model_profiles import load_model_profiles


def _render_qzone_model_options() -> str:
    """Render chat profiles into the QQ dynamic selector for a complete first paint."""
    try:
        profiles = [
            profile
            for profile in load_model_profiles()
            if str(profile.get("model_type") or "chat") == "chat"
        ]
    except Exception:
        profiles = []
    options = ['<option value="">当前聊天模型</option>']
    options.extend(
        f'<option value="{escape(str(profile.get("id") or ""), quote=True)}">'
        f'{escape(str(profile.get("name") or profile.get("model") or "未命名模型"))} · '
        f'{escape(str(profile.get("model") or ""))}</option>'
        for profile in profiles
        if str(profile.get("id") or "").strip()
    )
    return "".join(options)


def render_index() -> str:
    """拼接整页。

    ``body_*`` 都是**跨文件的半个 HTML**：每个片段关掉上一个面板、打开下一个，
    所以下面的顺序就是文档结构本身，重排会直接产出坏 DOM。面板顺序固定为
    模型 → 用户中心 → 测试 → 评测 → 高级；``BODY_VOICE_SERVICE``
    与 ``BODY_QQ_MUSIC`` 都落在「高级」面板内部，由 ``BODY_TAIL`` 统一收尾。
    Minecraft 女仆面板已迁出到 AI_vtuber 的后台 WebUI（游戏与女仆），本页不再持有它。

    同理，``script_*`` 里存在跨文件的函数（函数头在 A 文件、函数体在 B 文件），
    调整顺序前先确认相邻文件之间的函数边界没有被拆断。
    """

    body_users = BODY_USERS.replace(
        '<select id="qzoneGlobalModelProfile"><option value="">当前聊天模型</option></select>',
        f'<select id="qzoneGlobalModelProfile">{_render_qzone_model_options()}</select>',
        1,
    )
    return "".join(
        (
            DOCUMENT_HEAD,
            BODY_SHELL,
            BODY_MODEL,
            body_users,
            BODY_EVALUATION,
            BODY_ADVANCED,
            BODY_QQ_MUSIC,
            BODY_TAIL,
            SCRIPT_CORE,
            SCRIPT_ACCOUNT,
            SCRIPT_EVALUATION,
            SCRIPT_SUMMARY,
            SCRIPT_QQ_MUSIC,
            SCRIPT_STATUS,
            SCRIPT_MODELS,
            SCRIPT_PROACTIVE,
            SCRIPT_DIRECTORY,
            SCRIPT_QZONE,
            SCRIPT_SERVICES,
            SCRIPT_STRATEGY,
            SCRIPT_MEMORY,
            SCRIPT_VOICE_TEST,
        )
    )


__all__ = ["render_index"]
