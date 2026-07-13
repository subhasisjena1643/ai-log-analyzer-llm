"""
backend/integrations/base.py

Provider interface. Every knowledge source (Confluence, Jira, Demo, and later
Outlook) implements ContextProvider, so the reasoner can query them uniformly and
gracefully skip any that aren't connected ("more-the-merrier" — optional sources).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from .models import ConnectionState, RetrievedDoc


class ContextProvider(ABC):
    """A searchable source of prior knowledge/incidents used to augment RCA."""

    name: str = "base"
    kind_label: str = "knowledge"

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def state(self) -> ConnectionState:
        ...

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        """Return the most relevant docs for a (already-redacted) query string.

        Implementations MUST be resilient: on any error or when not connected they
        return an empty list rather than raising, so one bad source never breaks the
        overall analysis.
        """
        ...
