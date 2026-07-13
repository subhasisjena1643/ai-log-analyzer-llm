"""
backend/integrations/registry.py

Holds the active knowledge providers for the server session. Live credentials are
kept ONLY here, in memory — never persisted to disk or config. Demo Mode is always
available so retrieval works with zero connections.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from src.services.embedding_service import EmbeddingService
from .base import ContextProvider
from .demo_provider import DemoProvider
from .models import ConnectionState, RetrievedDoc
from .rest_providers import ConfluenceProvider, JiraProvider


class ProviderRegistry:
    """Thread-safe registry of connected providers plus the always-on demo provider."""

    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self._lock = threading.RLock()
        self._demo = DemoProvider(embedding_service)
        self._live: Dict[str, ContextProvider] = {}

    # -- connection management ---------------------------------------------

    def connect_confluence(self, base_url: str, email: str, token: str, spaces: Optional[List[str]] = None) -> ConnectionState:
        p = ConfluenceProvider(base_url, email, token, spaces)
        st = p.test()
        with self._lock:
            if st.connected:
                self._live["confluence"] = p
            else:
                self._live.pop("confluence", None)
        return st

    def connect_jira(self, base_url: str, email: str, token: str, jql: Optional[str] = None) -> ConnectionState:
        p = JiraProvider(base_url, email, token, jql)
        st = p.test()
        with self._lock:
            if st.connected:
                self._live["jira"] = p
            else:
                self._live.pop("jira", None)
        return st

    def disconnect(self, provider: str) -> None:
        with self._lock:
            self._live.pop(provider, None)

    # -- status ------------------------------------------------------------

    def states(self, demo_mode: bool) -> List[ConnectionState]:
        with self._lock:
            live = list(self._live.values())
        out = [self._demo.state()]
        if not demo_mode:
            for name in ("confluence", "jira"):
                p = next((x for x in live if x.name == name), None)
                out.append(p.state() if p else ConnectionState(provider=name, connected=False, mode="live", detail="Not connected"))
        return out

    # -- retrieval ---------------------------------------------------------

    def active_providers(self, demo_mode: bool) -> List[ContextProvider]:
        """Which providers to query. Demo Mode uses only the synthetic source;
        live mode queries any connected real sources (optional / more-the-merrier)."""
        if demo_mode:
            return [self._demo]
        with self._lock:
            live = list(self._live.values())
        # If nothing is connected, fall back to demo so the feature still works.
        return live if live else [self._demo]

    def search_all(self, query: str, demo_mode: bool, top_k: int = 5) -> List[RetrievedDoc]:
        results: List[RetrievedDoc] = []
        for provider in self.active_providers(demo_mode):
            results.extend(provider.search(query, top_k=top_k))
        # Best score first; keep the strongest across sources
        results.sort(key=lambda d: d.score, reverse=True)
        return results[: top_k * 2]
