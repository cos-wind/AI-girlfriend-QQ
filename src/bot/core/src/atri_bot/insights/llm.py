"""DeepSeek/OpenAI 兼容的结构化输出客户端。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from atri_bot.llm_tools.ollama_completion import is_local_endpoint
from atri_shared.networking import tls_context
from atri_shared.runtime.inference_lock import InferencePriority, inference_resource_lease
from atri_shared.runtime.services import ensure_ollama_service, release_ollama_model


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

    async def _post_completion(self, client, *, headers, payload):
        url = f"{self.base_url}/chat/completions"
        if not is_local_endpoint(self.base_url):
            return await client.post(url, headers=headers, json=payload)
        # Evaluation and summaries share the same GPU as foreground chat.
        # Yield between JSON-format attempts so queued chat can run first.
        async with inference_resource_lease(
            f"insights:{self.model}",
            timeout_seconds=self.timeout,
            priority=InferencePriority.BACKGROUND,
        ):
            if not await ensure_ollama_service(timeout_seconds=15.0):
                raise RuntimeError("本地评测模型服务暂时不可用")
            try:
                return await client.post(url, headers=headers, json=payload)
            finally:
                await release_ollama_model(self.model, self.base_url)

    async def check_connection(self) -> None:
        """验证凭据和接口可达性，不发送评测正文也不消耗模型额度。"""
        if not self.api_key:
            raise RuntimeError("未配置 EVALUATION_API_KEY 或 DEEPSEEK_API_KEY")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            verify=tls_context(),
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
        """只为 JSON 格式异常重试一次；网络与服务错误不重复消耗等待。"""
        if not self.api_key:
            raise RuntimeError("未配置 EVALUATION_API_KEY 或 DEEPSEEK_API_KEY")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            verify=tls_context(),
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
                    response = await self._post_completion(client, headers=headers, payload=payload)
                    response.raise_for_status()
                    data = response.json()
                    choice = (data.get("choices") or [{}])[0]
                    message = choice.get("message") or {}
                    content = str(message.get("content") or "").strip()
                    if not content:
                        raise ValueError("DeepSeek 返回了空的 JSON content")
                    return parse_json_object(content)
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    # Some OpenAI-compatible providers reject response_format.
                    # Auth, quota, overload and server errors are not JSON errors.
                    if attempt or exc.response.status_code not in {400, 422}:
                        break
                except httpx.RequestError as exc:
                    last_error = exc
                    break
                except (KeyError, TypeError, ValueError) as exc:
                    last_error = exc
        raise RuntimeError(f"结构化模型请求失败：{last_error}") from last_error
