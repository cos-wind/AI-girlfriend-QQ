"""低耦合的记忆检索边界。

该包只负责把可检索内容压缩成对话上下文；它不修改 JSON 记忆事实源，
也不依赖人格、OneBot 或 WebUI。这样检索故障可安全退回旧记忆逻辑。
"""

from .planner import ContextRetrievalPlanner, RetrievalSettings
from .repository import SemanticMemoryRepository

__all__ = ["ContextRetrievalPlanner", "RetrievalSettings", "SemanticMemoryRepository"]
