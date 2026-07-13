"""
backend/core/redaction.py

NDA-safe de-identification layer (requirements #4 and #6).

Every piece of free text that leaves the raw ingestion boundary — anything that is
stored, sent to the LLM, embedded, or returned to the frontend — is passed through
the Redactor first. The goal is a *neutral* diagnostic context: real client names,
site identifiers, and personal / secret data are replaced with stable neutral tokens
so that root-cause reasoning is preserved while confidential information is not.

Design notes:
  - Redaction is deterministic: the same input always maps to the same token, so
    correlation across files still works (e.g. the same email always becomes
    <EMAIL_1>), but the original value never appears downstream.
  - Named-entity terms (client / customer / site names) are fully configurable at
    runtime so an operator can add their own confidential terms without code changes,
    and no client name is hard-coded as "special".
  - The layer is conservative about high-signal secrets (AWS keys, bearer tokens,
    private keys) and always removes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Built-in patterns (ordered — most specific first)
# ---------------------------------------------------------------------------

# Each entry: (label, compiled regex). Label drives the neutral token name.
_BUILTIN_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    # Secrets — always removed, never counter-tokenized with a hint of the value
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.DOTALL)),
    ("BEARER_TOKEN", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9\-._~+/]{20,}=*")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("SECRET", re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|pwd|token)\b\s*[:=]\s*[\"']?([^\s\"']{6,})")),
    # PII
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("IPV4", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    ("IPV6", re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b")),
    ("MAC", re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]){12,15}\d\b")),
    # Phone: strict formats only, to avoid clobbering log timestamps / ports / ids.
    # Matches E.164 international (+CC ...) or clearly punctuated national numbers.
    ("PHONE", re.compile(
        r"(?<![\w:.])(?:"
        r"\+\d{1,3}[\s.-]?\(?\d{2,4}\)?(?:[\s.-]?\d{2,4}){2,4}"        # +44 (20) 7946 0958
        r"|\(\d{3}\)[\s.-]?\d{3}[\s.-]?\d{4}"                          # (415) 555-0132
        r"|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b"                            # 415-555-0132
        r")(?![\w:.])"
    )),
]

# Secret labels whose captured value must be discarded entirely (not just tokenized)
_HARD_SECRET_LABELS = {"AWS_KEY", "PRIVATE_KEY", "BEARER_TOKEN", "JWT", "SECRET"}


@dataclass
class RedactionConfig:
    """Runtime-tunable redaction settings.

    confidential_terms: operator-supplied client / customer / site names to neutralize.
                        Matching is whole-word and case-insensitive.
    enable_pii:         toggle the built-in PII/secret patterns.
    placeholder_prefix: token style, e.g. "CLIENT" -> "<CLIENT_1>".
    """

    confidential_terms: List[str] = field(default_factory=list)
    enable_pii: bool = True
    redact_numbers_over: int = 0  # if >0, mask standalone digit runs at least this long


@dataclass
class RedactionResult:
    text: str
    replacements: int
    token_map: Dict[str, str]  # neutral token -> label (never the original value)


class Redactor:
    """Deterministic, stateful de-identifier.

    A single Redactor instance keeps one token counter per label across all calls,
    so repeated values collapse to the same token within an analysis run. Create a
    fresh Redactor per analysis job to avoid cross-job leakage of the token map.
    """

    def __init__(self, config: Optional[RedactionConfig] = None):
        self.config = config or RedactionConfig()
        self._counters: Dict[str, int] = {}
        self._value_to_token: Dict[str, str] = {}
        self.token_map: Dict[str, str] = {}

        # Compile confidential term patterns (whole word, case-insensitive)
        self._term_patterns: List[Tuple[str, "re.Pattern[str]"]] = []
        for term in self.config.confidential_terms:
            term = term.strip()
            if not term:
                continue
            self._term_patterns.append(
                ("CLIENT", re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE))
            )

    # -- token allocation ---------------------------------------------------

    def _token_for(self, label: str, value: str) -> str:
        """Return a stable neutral token for (label, value)."""
        key = f"{label}::{value.lower()}"
        if key in self._value_to_token:
            return self._value_to_token[key]
        self._counters[label] = self._counters.get(label, 0) + 1
        token = f"<{label}_{self._counters[label]}>"
        self._value_to_token[key] = token
        self.token_map[token] = label
        return token

    # -- public API ---------------------------------------------------------

    def redact(self, text: Optional[str]) -> str:
        """Redact a single string, returning the neutralized text."""
        return self.redact_verbose(text).text

    def redact_verbose(self, text: Optional[str]) -> RedactionResult:
        if not text:
            return RedactionResult(text="" if text is None else text, replacements=0, token_map={})

        replacements = 0
        redacted = text

        # 1) Built-in PII / secret patterns FIRST. Structured values (emails, keys,
        #    hostnames) may embed a confidential term; collapsing the whole value to a
        #    token here guarantees the surrounding local-part/host is neutralized too,
        #    instead of leaking e.g. "john.doe@<CLIENT_1>.com".
        if self.config.enable_pii:
            for label, pattern in _BUILTIN_PATTERNS:
                def _sub_builtin(m, _label=label):
                    nonlocal replacements
                    replacements += 1
                    if _label in _HARD_SECRET_LABELS:
                        # Discard the value entirely — a shared token per label is enough
                        return f"<{_label}_REDACTED>"
                    return self._token_for(_label, m.group(0))
                redacted = pattern.sub(_sub_builtin, redacted)

        # 2) Operator-defined confidential terms (client / customer / site names) that
        #    remain in prose, paths, or URLs not covered by the structured patterns.
        for label, pattern in self._term_patterns:
            def _sub_term(m, _label=label):
                nonlocal replacements
                replacements += 1
                return self._token_for(_label, m.group(0))
            redacted = pattern.sub(_sub_term, redacted)

        # 3) Optional long standalone numeric runs (account ids, ticket numbers, etc.)
        if self.config.redact_numbers_over > 0:
            n = self.config.redact_numbers_over
            num_pat = re.compile(rf"(?<!\w)\d{{{n},}}(?!\w)")

            def _sub_num(m):
                nonlocal replacements
                replacements += 1
                return self._token_for("NUM", m.group(0))
            redacted = num_pat.sub(_sub_num, redacted)

        return RedactionResult(text=redacted, replacements=replacements, token_map=dict(self.token_map))

    def redact_lines(self, lines: List[str]) -> List[str]:
        return [self.redact(line) for line in (lines or [])]

    def redact_mapping(self, data: Optional[dict]) -> dict:
        """Recursively redact all string values in a (possibly nested) dict/list."""
        return self._walk(data) if data else (data or {})

    def _walk(self, obj):
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {k: self._walk(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._walk(v) for v in obj]
        return obj

    @property
    def summary(self) -> Dict[str, int]:
        """Count of neutral tokens issued per label — safe to surface in the UI."""
        counts: Dict[str, int] = {}
        for label in self.token_map.values():
            counts[label] = counts.get(label, 0) + 1
        return counts
