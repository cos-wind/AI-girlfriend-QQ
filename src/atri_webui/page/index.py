from __future__ import annotations

from .document_head import PART as DOCUMENT_HEAD
from .body_shell import PART as BODY_SHELL
from .body_model import PART as BODY_MODEL
from .body_voice import PART as BODY_VOICE
from .body_users import PART as BODY_USERS
from .body_evaluation import PART as BODY_EVALUATION
from .body_minecraft import PART as BODY_MINECRAFT
from .body_advanced import PART as BODY_ADVANCED
from .script_core import PART as SCRIPT_CORE
from .script_evaluation import PART as SCRIPT_EVALUATION
from .script_summary import PART as SCRIPT_SUMMARY
from .script_minecraft import PART as SCRIPT_MINECRAFT
from .script_voice import PART as SCRIPT_VOICE
from .script_music import PART as SCRIPT_MUSIC
from .script_singing import PART as SCRIPT_SINGING
from .script_status import PART as SCRIPT_STATUS
from .script_models import PART as SCRIPT_MODELS
from .script_proactive import PART as SCRIPT_PROACTIVE
from .script_directory import PART as SCRIPT_DIRECTORY
from .script_qzone import PART as SCRIPT_QZONE
from .script_memory import PART as SCRIPT_MEMORY
from .script_voice_test import PART as SCRIPT_VOICE_TEST


def render_index() -> str:
    return "".join(
        (
            DOCUMENT_HEAD,
            BODY_SHELL,
            BODY_MODEL,
            BODY_VOICE,
            BODY_USERS,
            BODY_EVALUATION,
            BODY_MINECRAFT,
            BODY_ADVANCED,
            SCRIPT_CORE,
            SCRIPT_EVALUATION,
            SCRIPT_SUMMARY,
            SCRIPT_MINECRAFT,
            SCRIPT_VOICE,
            SCRIPT_MUSIC,
            SCRIPT_SINGING,
            SCRIPT_STATUS,
            SCRIPT_MODELS,
            SCRIPT_PROACTIVE,
            SCRIPT_DIRECTORY,
            SCRIPT_QZONE,
            SCRIPT_MEMORY,
            SCRIPT_VOICE_TEST
        )
    )


__all__ = ["render_index"]
