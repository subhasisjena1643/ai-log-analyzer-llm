"""
backend/integrations/demo_provider.py

Demo Mode knowledge provider. Semantically searches the synthetic Confluence/Jira
dataset using the same embedding model the KB already uses (no extra disk cost).
Always "connected" — this is what lets users with no Atlassian access test the full
retrieval + reasoning experience.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from src.services.embedding_service import EmbeddingService
from ..demo.dataset import all_documents
from .base import ContextProvider
from .models import ConnectionState, RetrievedDoc


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a) + 1e-9)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return b_norm @ a_norm


class DemoProvider(ContextProvider):
    name = "demo"
    kind_label = "synthetic knowledge"

    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self._embed = embedding_service or EmbeddingService()
        self._docs = all_documents()
        # Precompute embeddings once (title + labels + body carry the signal)
        corpus = [
            f"{d['title']}. {' '.join(d.get('labels', []))}. {d.get('body', '')}"
            for d in self._docs
        ]
        self._matrix = np.asarray(self._embed.encode(corpus), dtype=np.float32)

    def is_connected(self) -> bool:
        return True

    def state(self) -> ConnectionState:
        return ConnectionState(
            provider="demo", connected=True, mode="demo",
            detail=f"{len(self._docs)} synthetic runbooks & incidents",
        )

    def search(self, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        if not query.strip():
            return []
        try:
            q = np.asarray(self._embed.encode_single(query), dtype=np.float32)
            scores = _cosine(q, self._matrix)
            order = np.argsort(scores)[::-1][:top_k]
            out: List[RetrievedDoc] = []
            for idx in order:
                d = self._docs[int(idx)]
                score = float(scores[int(idx)])
                if score < 0.15:  # drop weak matches
                    continue
                body = d.get("body", "")
                out.append(RetrievedDoc(
                    source=d["_source"],
                    kind=d["_kind"],
                    id=d["id"],
                    title=d["title"],
                    snippet=body[:280] + ("…" if len(body) > 280 else ""),
                    url=None,
                    score=score,
                    status=d.get("status"),
                    labels=d.get("labels", []),
                    extra={"space": d.get("space"), "project": d.get("project"), "body": body},
                ))
            return out
        except Exception:
            return []
