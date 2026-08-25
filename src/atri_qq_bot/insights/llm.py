"""DeepSeek/OpenAI 兼容的结构化输出客户端。"""

from __future__ import annotations

import json
from typing import Any

import httpx


def parse_json_object(raw: str) -> dict[str, Any]:
    """容忍 Markdown 代码围栏，但拒绝非对象结果。"""
    value = str(raw or "").strip()
    if value.startswith("```"):
        value = value.strip("`").strip()
        if value.lower().startswith("json"):
            value = value[4:].strip()
    # 少数兼容服务会在 JSON 前后补一句话，安全地截取最外层对象。
    if not value.startswith("{") and "{" in value and "}" in value:
        value = value[value.find("{") : value.rfind("}") + 1]
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("模型结构化输出不是 JSON 对象")
    return parsed


class StructuredLLMClient:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.api_key = str(api_key)
        self.model = str(model)
        self.timeout = float(timeout)

    async def check_connection(self) -> None:
        """验证凭据和接口可达性，不发送评测正文也不消耗模型额度。"""
        if not self.api_key:
            raise RuntimeError("未配置 EVALUATION_API_KEY 或 DEEPSEEK_API_KEY")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
        ) as client:
            response = await client.get(f"{self.base_url}/models", headers=headers)
            if response.status_code == 401:
                raise RuntimeError("DeepSeek API Key 无效或已过期（HTTP 401），请重新配置")
            response.raise_for_status()

    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 2200,
    ) -> dict[str, Any]:
        """请求 JSON Output；空内容或格式异常时做一次克制的文本 JSON 重试。"""
        if not self.api_key:
            raise RuntimeError("未配置 EVALUATION_API_KEY 或 DEEPSEEK_API_KEY")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
        ) as client:
            for attempt in range(2):
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": prompt
                            + ("\n\n再次强调：仅输出一个完整 JSON 对象，不能输出 Markdown。" if attempt else ""),
                        },
                    ],
                    "temperature": 0.0,
                    "max_tokens": int(max_tokens),
                }
                if attempt == 0:
                    payload["response_format"] = {"type": "json_object"}
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", headers=headers, json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    choice = (data.get("choices") or [{}])[0]
                    message = choice.get("message") or {}
                    content = str(message.get("content") or "").strip()
                    if not content:
                        raise ValueError("DeepSeek 返回了空的 JSON content")
                    return parse_json_object(content)
                except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    last_error = exc
        raise RuntimeError(f"结构化模型请求失败：{last_error}") from last_error
