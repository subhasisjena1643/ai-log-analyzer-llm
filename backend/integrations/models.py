"""
backend/integrations/models.py

Shared data shapes for the external-knowledge providers (Confluence, Jira, and the
Demo provider). Provider-agnostic so the reasoner and API don't care about source.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RetrievedDoc:
    """A single retrieved knowledge/incident item, normalized across sources."""
    source: str            # "confluence" | "jira" | "demo-confluence" | "demo-jira"
    kind: str              # "runbook" | "kb" | "incident" | "ticket"
    id: str
    title: str
    snippet: str           # short, redaction-safe excerpt
    url: Optional[str] = None
    score: float = 0.0     # semantic similarity 0..1
    status: Optional[str] = None      # e.g. Jira status / resolution
    labels: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["score"] = round(float(self.score), 4)
        return d


@dataclass
class ConnectionState:
    """Runtime connection status for one provider — never persisted to disk."""
    provider: str
    connected: bool = False
    mode: str = "demo"     # "demo" | "live"
    account: Optional[str] = None    # e.g. the email that authenticated (display only)
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
