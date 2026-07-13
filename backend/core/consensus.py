"""
backend/core/consensus.py

High-assurance "Venn" consensus reasoning (self-consistency ensemble).

Runs the same grounded RCA prompt N independent times, then keeps only the claims
that MULTIPLE runs agree on (the intersection) and flags single-run outliers as
likely hallucinations. The consensus step itself is deterministic — it uses the
existing embedding model to cluster semantically-equivalent claims — so it adds no
extra LLM call beyond the N samples.

Everything fed in is already redacted by the caller.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List

import numpy as np


# Bullet lines under these sections carry the substantive claims worth voting on.
_CLAIM_SECTIONS = ("root cause", "suggested fix", "impact")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)")
_HEADING = re.compile(r"^\s*#{1,6}\s*(.+?)\s*$")


@dataclass
class ConsensusClaim:
    text: str
    support: int          # how many of the N runs asserted this
    section: str


@dataclass
class ConsensusResult:
    consensus_text: str
    agreement_score: float          # 0..1 — share of claims that reached majority
    runs: int
    consensus_claims: List[ConsensusClaim] = field(default_factory=list)
    flagged_claims: List[ConsensusClaim] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "runs": self.runs,
            "agreement_score": round(self.agreement_score, 3),
            "consensus_claims": [{"text": c.text, "support": c.support, "section": c.section} for c in self.consensus_claims],
            "flagged_claims": [{"text": c.text, "support": c.support, "section": c.section} for c in self.flagged_claims],
        }


def _extract_claims(markdown: str) -> List[tuple]:
    """Return [(section, claim_text), ...] for bullets under the claim sections."""
    section = ""
    out: List[tuple] = []
    for line in (markdown or "").splitlines():
        h = _HEADING.match(line)
        if h:
            section = h.group(1).strip().lower()
            continue
        b = _BULLET.match(line)
        if b and any(s in section for s in _CLAIM_SECTIONS):
            claim = b.group(1).strip().rstrip(".")
            claim = re.sub(r"\*\*(.+?)\*\*", r"\1", claim)  # strip bold
            if len(claim) > 8:
                # normalize the section label to one of the known buckets
                bucket = next((s for s in _CLAIM_SECTIONS if s in section), section)
                out.append((bucket, claim))
    return out


def run_consensus(
    generate_fn: Callable[[float], str],
    embed_fn: Callable[[List[str]], np.ndarray],
    n: int = 3,
    sim_threshold: float = 0.45,
) -> ConsensusResult:
    """Generate N samples (temperature-varied) and intersect their claims.

    generate_fn(temperature) -> one RCA markdown string.
    embed_fn(list[str]) -> (len, dim) embedding matrix.
    """
    n = max(2, min(n, 5))
    temps = [round(0.2 + 0.6 * i / (n - 1), 2) for i in range(n)]  # spread 0.2..0.8
    samples = [generate_fn(t) for t in temps]

    # Collect claims with their run index
    per_run_claims: List[List[tuple]] = [_extract_claims(s) for s in samples]
    flat: List[tuple] = []  # (run_idx, section, text)
    for run_idx, claims in enumerate(per_run_claims):
        for section, text in claims:
            flat.append((run_idx, section, text))

    if not flat:
        # No parseable claims (e.g. all runs returned prose) — fall back to first sample.
        return ConsensusResult(consensus_text=samples[0], agreement_score=0.0, runs=n)

    texts = [t[2] for t in flat]
    vecs = np.asarray(embed_fn(texts), dtype=np.float32)
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)

    # Greedy clustering of semantically-equivalent claims
    clusters: List[Dict] = []
    for i, (run_idx, section, text) in enumerate(flat):
        placed = False
        for cl in clusters:
            if float(vecs[i] @ cl["centroid"]) >= sim_threshold:
                cl["runs"].add(run_idx)
                cl["members"].append((i, text))
                cl["centroid"] = (cl["centroid"] * cl["k"] + vecs[i]) / (cl["k"] + 1)
                cl["k"] += 1
                placed = True
                break
        if not placed:
            clusters.append({"centroid": vecs[i].copy(), "k": 1, "runs": {run_idx},
                             "members": [(i, text)], "section": section})

    majority = math.ceil(n / 2)
    consensus, flagged = [], []
    for cl in clusters:
        support = len(cl["runs"])
        # representative = the shortest member (usually the cleanest phrasing)
        rep = min((m[1] for m in cl["members"]), key=len)
        claim = ConsensusClaim(text=rep, support=support, section=cl["section"])
        (consensus if support >= majority else flagged).append(claim)

    consensus.sort(key=lambda c: (-c.support, c.section))
    flagged.sort(key=lambda c: c.section)
    total = len(consensus) + len(flagged)
    agreement = len(consensus) / total if total else 0.0

    text = _render(consensus, flagged, n)
    return ConsensusResult(
        consensus_text=text, agreement_score=agreement, runs=n,
        consensus_claims=consensus, flagged_claims=flagged,
    )


def _render(consensus: List[ConsensusClaim], flagged: List[ConsensusClaim], n: int) -> str:
    lines = [f"### Consensus Root Cause Analysis ({n}-run agreement)"]
    by_section: Dict[str, List[ConsensusClaim]] = {}
    for c in consensus:
        by_section.setdefault(c.section, []).append(c)

    labels = {"root cause": "Root Cause", "impact": "Impact", "suggested fix": "Suggested Fix"}
    for section in ("root cause", "impact", "suggested fix"):
        items = by_section.get(section)
        if not items:
            continue
        lines.append(f"\n#### {labels.get(section, section.title())}")
        for c in items:
            lines.append(f"- {c.text}  _(agreed by {c.support}/{n})_")

    if flagged:
        lines.append("\n#### ⚠ Flagged — single-run claims (unverified, possible hallucination)")
        for c in flagged:
            lines.append(f"- {c.text}  _(only {c.support}/{n})_")
    return "\n".join(lines)
