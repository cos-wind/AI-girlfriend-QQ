from __future__ import annotations

from ..prompting import load_prompt


# 群聊规则由 docs/prompts/group_chat.md 维护，代码只保留加载 seam。
GROUP_PROMPT = load_prompt("group_chat")

