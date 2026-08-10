"""Ollama 嵌入适配器。

只使用标准库 HTTP；调用方必须显式启用，且 keep_alive=0，避免 bge-m3 常驻
占用内存。网络/模型错误会抛出可恢复异常，由检索规划器继续使用 FTS5。
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaEmbeddingClient:
    def __init__(
        self,
        model: str = "bge-m3:latest",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 3.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(0.5, min(20.0, float(timeout_seconds)))

    def embed(self, text: str) -> list[float]:
        payload = json.dumps(
            {"model": self.model, "input": str(text or ""), "keep_alive": "0"},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self.base_url + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama embedding unavailable: {exc}") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        vector = vectors[0] if isinstance(vectors, list) and vectors else None
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Ollama embedding returned no vector")
        try:
            return [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Ollama embedding returned an invalid vector") from exc
