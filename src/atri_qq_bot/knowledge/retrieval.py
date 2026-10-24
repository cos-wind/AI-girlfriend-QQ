"""Reuse the configured embedding service only when offline vectors already exist."""
from __future__ import annotations

import logging
from typing import Any

from ..retrieval.embeddings import OllamaEmbeddingClient
from ..runtime.inference_lock import inference_resource_lease_sync
from .store import KnowledgeStore

LOG = logging.getLogger(__name__)


def retrieve(store: KnowledgeStore, scope: str, query: str, day: str = "", *, limit: int = 8,
             config: Any = None) -> list[dict[str, Any]]:
    vector = None
    model = str(getattr(config, "memory_embedding_model", "bge-m3:latest"))
    if getattr(config, "memory_vector_enabled", False) and store.index.embedding_count(model):
        try:
            with inference_resource_lease_sync(f"embedding:{model}", timeout_seconds=0.0):
                vector = OllamaEmbeddingClient(model, getattr(config, "memory_embedding_base_url", "http://127.0.0.1:11434"),
                                               getattr(config, "memory_embedding_timeout_seconds", 2.0)).embed(query)
        except Exception as exc:
            LOG.debug("knowledge vector lookup fell back to FTS: %s", exc)
    return store.search(scope, query, day, limit, vector=vector, model=model)
