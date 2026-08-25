"""延迟加载的 SentenceTransformers 适配器。"""

from __future__ import annotations

import math
import threading
from typing import Any, Sequence


class SemanticEncoder:
    """只有后台任务真正需要向量时才加载模型，避免增加机器人启动延迟。"""

    def __init__(self, model_name: str, *, local_only: bool = False) -> None:
        self.model_name = str(model_name)
        self.local_only = bool(local_only)
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise RuntimeError(
                        "未安装 sentence-transformers；请执行 pip install -r requirements.txt"
                    ) from exc
                self._model = SentenceTransformer(
                    self.model_name,
                    local_files_only=self.local_only,
                )
        return self._model

    def encode(self, texts: Sequence[str]) -> Any:
        if not texts:
            return []
        model = self._load()
        return model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=min(32, max(1, len(texts))),
        )

    def similarity(self, left: str, right: str) -> float:
        vectors = self.encode([str(left), str(right)])
        # 向量已归一化，点积等价于余弦相似度；避免依赖 torch 工具函数。
        value = float(sum(float(a) * float(b) for a, b in zip(vectors[0], vectors[1])))
        return max(-1.0, min(1.0, value)) if math.isfinite(value) else 0.0

