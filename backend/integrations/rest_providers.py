"""
backend/integrations/rest_providers.py

Live Confluence & Jira providers using runtime credentials the user supplies IN THE
APP (never hardcoded, never written to disk). Credentials live only in the in-memory
registry for the server session.

These are built to the Atlassian Cloud REST API. They are network-guarded: any error
returns an empty result so a flaky/unauthorized connection never breaks analysis.
Because live Atlassian access is not available during development, these are exercised
via the registry's connection test; Demo Mode remains the verified default.
"""

from __future__ import annotations

import base64
from typing import List, Optional
from urllib.parse import quote

import requests

from .base import ContextProvider
from .models import ConnectionState, RetrievedDoc

_TIMEOUT = 12


def _auth_header(email: str, token: str) -> dict:
    raw = f"{email}:{token}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
            "Accept": "application/json"}


class ConfluenceProvider(ContextProvider):
    name = "confluence"
    kind_label = "runbooks & KB"

    def __init__(self, base_url: str, email: str, token: str, spaces: Optional[List[str]] = None):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self._token = token
        self.spaces = [s.strip() for s in (spaces or []) if s.strip()]
        self._ok = False
        self._detail = ""

    def test(self) -> ConnectionState:
        try:
            r = requests.get(
                f"{self.base_url}/wiki/rest/api/space",
                headers=_auth_header(self.email, self._token),
                params={"limit": 1}, timeout=_TIMEOUT,
            )
            self._ok = r.status_code == 200
            self._detail = "Connected" if self._ok else f"HTTP {r.status_code}"
        except Exception as e:
            self._ok = False
            self._detail = str(e)[:120]
        return self.state()

    def is_connected(self) -> bool:
        return self._ok

    def state(self) -> ConnectionState:
        return ConnectionState(provider="confluence", connected=self._ok, mode="live",
                               account=self.email, detail=self._detail)

    def search(self, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        if not self._ok or not query.strip():
            return []
        try:
            cql = f'text ~ "{query}"'
            if self.spaces:
                cql += " and space in (" + ",".join(f'"{s}"' for s in self.spaces) + ")"
            r = requests.get(
                f"{self.base_url}/wiki/rest/api/search",
                headers=_auth_header(self.email, self._token),
                params={"cql": cql, "limit": top_k}, timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                return []
            out: List[RetrievedDoc] = []
            for item in r.json().get("results", []):
                content = item.get("content", {}) or {}
                title = content.get("title") or item.get("title", "Untitled")
                excerpt = (item.get("excerpt") or "").replace("@@@hl@@@", "").replace("@@@endhl@@@", "")
                out.append(RetrievedDoc(
                    source="confluence", kind="runbook",
                    id=str(content.get("id", "")), title=title,
                    snippet=excerpt[:280],
                    url=(self.base_url + item.get("url", "")) if item.get("url") else None,
                    score=0.0,
                ))
            return out
        except Exception:
            return []


class JiraProvider(ContextProvider):
    name = "jira"
    kind_label = "incidents & tickets"

    def __init__(self, base_url: str, email: str, token: str, jql: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self._token = token
        self.jql_scope = (jql or "").strip()
        self._ok = False
        self._detail = ""

    def test(self) -> ConnectionState:
        try:
            r = requests.get(
                f"{self.base_url}/rest/api/3/myself",
                headers=_auth_header(self.email, self._token), timeout=_TIMEOUT,
            )
            self._ok = r.status_code == 200
            self._detail = "Connected" if self._ok else f"HTTP {r.status_code}"
        except Exception as e:
            self._ok = False
            self._detail = str(e)[:120]
        return self.state()

    def is_connected(self) -> bool:
        return self._ok

    def state(self) -> ConnectionState:
        return ConnectionState(provider="jira", connected=self._ok, mode="live",
                               account=self.email, detail=self._detail)

    def search(self, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        if not self._ok or not query.strip():
            return []
        try:
            terms = query.replace('"', " ")
            jql = f'text ~ "{terms}"'
            if self.jql_scope:
                jql = f"({self.jql_scope}) and " + jql
            r = requests.get(
                f"{self.base_url}/rest/api/3/search",
                headers=_auth_header(self.email, self._token),
                params={"jql": jql, "maxResults": top_k,
                        "fields": "summary,status,labels,description"},
                timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                return []
            out: List[RetrievedDoc] = []
            for issue in r.json().get("issues", []):
                f = issue.get("fields", {})
                status = (f.get("status") or {}).get("name")
                out.append(RetrievedDoc(
                    source="jira", kind="incident",
                    id=issue.get("key", ""), title=f.get("summary", ""),
                    snippet=_plain_text(f.get("description"))[:280],
                    url=f"{self.base_url}/browse/{quote(issue.get('key', ''))}",
                    score=0.0, status=status, labels=f.get("labels", []),
                ))
            return out
        except Exception:
            return []


def _plain_text(adf) -> str:
    """Flatten Jira's Atlassian Document Format description into plain text."""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return ""
    parts: List[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text" and "text" in node:
                parts.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)
    walk(adf)
    return " ".join(parts)
