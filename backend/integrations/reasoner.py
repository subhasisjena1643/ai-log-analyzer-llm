"""
backend/integrations/reasoner.py

Retrieval-augmented reasoning (requirements #2 and #3).

Given the analysis result for an uploaded bundle, this:
  1. builds a compact, REDACTED problem signature from the RCA + evidence,
  2. retrieves the most similar prior runbooks (Confluence) and incidents (Jira),
  3. asks the LLM to reason like a senior SRE — matching the current problem to the
     closest known cases and producing a narrowed, step-by-step troubleshooting path,
     grounded ONLY in the retrieved evidence (with citations).

Everything sent to the LLM is redacted first; nothing confidential is stored.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.services.bedrock_llm import BedrockLLM
from backend.core.redaction import Redactor
from .models import RetrievedDoc
from .registry import ProviderRegistry


def build_problem_signature(result: Dict[str, Any]) -> str:
    """A short, source-agnostic description of the current problem for retrieval."""
    rca = result.get("rca", {})
    parts: List[str] = [
        result.get("meta", {}).get("query", ""),
        rca.get("error_type", ""),
        rca.get("automated_rca", ""),
    ]
    for line in result.get("evidence", {}).get("similar_errors", [])[:5]:
        parts.append(line)
    for summ in result.get("agents", {}).get("summaries", {}).values():
        parts.append(summ)
    text = "  ".join(p for p in parts if p)
    return text[:1200]


def _doc_text(d: RetrievedDoc) -> str:
    """Prefer the full body (demo) over the truncated snippet for extraction."""
    return (d.extra.get("body") if isinstance(d.extra, dict) else None) or d.snippet


def _extract_remediation(text: str, limit: int = 220) -> str:
    """Pull the remediation/fix clause out of a runbook/incident body."""
    for marker in ("Remediation:", "Fix:", "Recommended:"):
        i = text.find(marker)
        if i != -1:
            out = text[i + len(marker):].strip()
            break
    else:
        out = text.strip()
    out = out.rstrip(".").strip()
    return (out[:limit] + "...") if len(out) > limit else out


def _deterministic_narrowed(docs: List[RetrievedDoc]) -> str:
    """A grounded, cited troubleshooting synthesis built directly from retrieved docs.

    This is the guaranteed baseline: it never invents anything and always cites IDs,
    so the feature stays useful even when the LLM is throttled/unavailable.
    """
    if not docs:
        return ""
    runbooks = [d for d in docs if d.kind in ("runbook", "kb")]
    incidents = [d for d in docs if d.kind in ("incident", "ticket")]
    top = docs[0]

    lines: List[str] = ["### Closest Known Cases"]
    for d in docs[:4]:
        conf = "strong" if d.score >= 0.6 else "moderate" if d.score >= 0.4 else "weak"
        status = f", {d.status}" if d.status else ""
        lines.append(f"- **{d.id}** ({conf} match{status}) - {d.title}")

    lines.append("\n### Narrowed Root-Cause Hypothesis")
    lines.append(
        f"The current problem most closely matches **{top.id}** - {top.title}. "
        + (f"A prior incident (**{incidents[0].id}**) with a similar signature was resolved as: "
           f"{_extract_remediation(_doc_text(incidents[0]))}" if incidents else "")
    )

    lines.append("\n### Recommended Troubleshooting Path")
    # Only use runbooks that are a reasonable match; avoid dragging in weak, off-topic ones.
    path_runbooks = [d for d in runbooks if d.score >= 0.4] or runbooks[:1]
    step = 1
    for d in path_runbooks[:2]:
        rem = _extract_remediation(_doc_text(d))
        lines.append(f"{step}. Per **{d.id}** ({d.title}): {rem}")
        step += 1
    if incidents:
        lines.append(f"{step}. Cross-check against incident **{incidents[0].id}** - apply the verified fix if the signature confirms.")

    strong = [d for d in docs if d.score >= 0.6]
    level = "High" if strong else "Medium" if top.score >= 0.4 else "Low"
    cited = ", ".join(d.id for d in docs[:3])
    lines.append(f"\n### Confidence\n- **{level}** - based on retrieved matches {cited}.")
    return "\n".join(lines)


def _format_retrieved(docs: List[RetrievedDoc]) -> str:
    lines: List[str] = []
    for d in docs:
        tag = "RUNBOOK" if d.kind in ("runbook", "kb") else "INCIDENT"
        status = f" ({d.status})" if d.status else ""
        lines.append(f"[{tag} {d.id}{status}] {d.title}\n  {d.snippet}")
    return "\n".join(lines)


class RetrievalReasoner:
    def __init__(self, registry: ProviderRegistry, llm: BedrockLLM):
        self.registry = registry
        self.llm = llm

    def reason(
        self,
        result: Dict[str, Any],
        *,
        demo_mode: bool,
        redactor: Redactor,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        signature = redactor.redact(build_problem_signature(result))
        docs = self.registry.search_all(signature, demo_mode=demo_mode, top_k=top_k)

        if not docs:
            return {
                "available": False,
                "matches": [],
                "narrowed_analysis": "",
                "note": "No similar runbooks or incidents were retrieved.",
            }

        retrieved_block = redactor.redact(_format_retrieved(docs))
        prompt = self._prompt(signature, retrieved_block)

        # Deterministic, retrieval-grounded baseline that ALWAYS cites the matched IDs.
        grounded = _deterministic_narrowed(docs)

        narrowed = grounded
        used_llm = False
        try:
            llm_out = self.llm.generate(prompt, max_tokens=700, temperature=0.2)
            # Only trust the LLM output if it actually reasons over the retrieved
            # evidence (cites at least one runbook/incident ID). Otherwise the call
            # fell through to the generic canned fallback and we keep the grounded one.
            if llm_out and any(d.id in llm_out for d in docs):
                narrowed = llm_out
                used_llm = True
        except Exception:
            pass

        return {
            "available": True,
            "matches": [d.to_dict() for d in docs],
            "narrowed_analysis": narrowed,
            "grounded_in_retrieval": True,
            "llm_refined": used_llm,
            "sources": sorted({d.source for d in docs}),
        }

    @staticmethod
    def _prompt(signature: str, retrieved: str) -> str:
        return f"""You are a senior SRE performing incident triage. Below is the CURRENT problem \
(from live diagnostics) and a set of the most similar PRIOR runbooks and incidents retrieved from \
the knowledge base. Reason like an expert: match the current problem to the closest known case(s), \
explain WHY they match, and produce a narrowed, ordered troubleshooting path specific to this problem.

Rules:
- Use ONLY the retrieved evidence below. Do not invent runbooks, incidents, or fixes.
- Cite the runbook/incident IDs you rely on (e.g. INC-4021, RUNBOOK-DBPOOL).
- If the matches are weak, say so and give the single best next diagnostic step.

Return this structure:
### Closest Known Cases
- <ID> — one line on why it matches.
### Narrowed Root-Cause Hypothesis
### Recommended Troubleshooting Path
1. ...
### Confidence
- Low/Medium/High, citing the matched IDs.

=== CURRENT PROBLEM SIGNATURE ===
{signature}

=== RETRIEVED SIMILAR RUNBOOKS & INCIDENTS ===
{retrieved}
"""
