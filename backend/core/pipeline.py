"""
backend/core/pipeline.py

Framework-agnostic analysis pipeline extracted from the Streamlit app.py.

This is the single reusable entry point that both the FastAPI API and (optionally)
the legacy Streamlit UI can drive. It contains NO UI calls — progress is reported
through an optional callback, and all output is JSON-serializable.

Flow (mirrors app.py lines ~742-1033):
  1. Ingest a directory of already-saved files (archives extracted recursively).
  2. Run the Phase-3 distributed agent orchestration.
  3. Compute anomaly detection, time correlation, automated RCA.
  4. Generate the LLM RCA from redacted, neutralized context.
  5. Run the legacy RAG/KB lookup.
  6. Return a neutralized, JSON-safe result bundle + a redaction summary.

NDA neutrality (requirement #4): all free text that reaches the LLM, the response,
or persistent storage is passed through the Redactor first. Client/zone identifiers
are replaced with neutral placeholders before parsing.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import yaml

from src.services.log_reader import LogReader
from src.services.rag_engine import RAGEngine
from src.services.knowledge_base import KnowledgeBase
from src.services.template_rca import TemplateRCA
from src.services.archive_processor import ArchiveProcessor
from src.services.anomaly_detector import detect_error_anomaly
from src.services.time_correlation import correlate_errors_by_time
from src.services.automated_rca import generate_automated_rca
from src.services.bedrock_llm import BedrockLLM
from src.services.agent_framework import (
    FileClassifier, AgentOrchestrator, AgentResultMerger,
    AGENT_APP_LOG, AGENT_SQL, AGENT_PDF, AGENT_JVM,
    AGENT_PCAP, AGENT_AUDIO, AGENT_SRE_NOTES, AGENT_CONFIG,
)
from src.services.agents.app_log_agent import AppLogAgent
from src.services.agents.sql_agent import SQLAgent
from src.services.agents.pdf_agent import PDFAgent
from src.services.agents.jvm_agent import JVMAgent
from src.services.agents.pcap_agent import PCAPAgent
from src.services.agents.audio_agent import AudioAgent
from src.services.agents.sre_notes_agent import SRENotesAgent
from src.services.agents.config_agent import ConfigAgent

from backend.core.redaction import Redactor, RedactionConfig
from backend.core.serialization import to_jsonable, serialize_log_entry
from backend.core.ingestion import IngestionPlanner, IngestionProfile


ProgressCB = Callable[[str, str, float], None]

# Neutral metadata used in place of real client/zone/app identifiers (requirement #4).
NEUTRAL_ZONE = "GLOBAL"
NEUTRAL_CLIENT = "NEUTRAL"
NEUTRAL_APP = "APP"
NEUTRAL_VERSION = "0.0/0.0.0"


# ---------------------------------------------------------------------------
# Ported helpers (previously inline in app.py, UI-free versions)
# ---------------------------------------------------------------------------

def classify_error_type(log: str) -> str:
    log_lower = (log or "").lower()
    if "timeout" in log_lower:
        return "Timeout Issue"
    if "connection" in log_lower:
        return "Network Issue"
    if "error" in log_lower:
        return "Application Error"
    return "Other"


def format_archive_context_for_prompt(archive_context: Optional[dict]) -> str:
    if not archive_context:
        return ""
    parts: List[str] = []

    sql_ctx = archive_context.get("sql_context", {})
    if sql_ctx:
        parts.append("=== EXTRACTED DATABASE (SQL) DIAGNOSTICS ===")
        for file, data in sql_ctx.items():
            parts.append(f"File: {file}")
            if data.get("tables_found"):
                parts.append(f"Tables Found: {', '.join(data['tables_found'])}")
            if data.get("errors_found"):
                parts.append("SQL Errors/Exceptions Found:")
                for err in data["errors_found"][:5]:
                    parts.append(f"  - {err}")
            if data.get("queries_count"):
                parts.append(f"Total Queries Executed: {data['queries_count']}")
        parts.append("")

    pdf_ctx = archive_context.get("pdf_context", {})
    if pdf_ctx:
        parts.append("=== EXTRACTED HEALTHCHECK REPORT (PDF) ===")
        for file, data in pdf_ctx.items():
            parts.append(f"Report File: {file}")
            for fail in data.get("failures", [])[:5]:
                parts.append(f"  - [FAILED] {fail}")
            for warn in data.get("warnings", [])[:5]:
                parts.append(f"  - [WARN] {warn}")
        parts.append("")

    mem_ctx = archive_context.get("memory_context", {})
    if mem_ctx:
        parts.append("=== EXTRACTED JVM & HEAP MEMORY DIAGNOSTICS ===")
        for file, data in mem_ctx.items():
            parts.append(f"Diagnostic File: {file}")
            if data.get("heap_max_mb") or data.get("heap_used_mb"):
                parts.append(f"  Heap Used: {data.get('heap_used_mb', 'N/A')} MB / Max: {data.get('heap_max_mb', 'N/A')} MB")
            if data.get("thread_states"):
                states = ", ".join(f"{k}: {v}" for k, v in data["thread_states"].items() if v > 0)
                parts.append(f"  JVM Thread Counts by State: {states}")
            for pause in data.get("gc_pauses", [])[:3]:
                parts.append(f"    * {pause}")
        parts.append("")

    inf_ctx = archive_context.get("inference_context", {})
    if inf_ctx:
        parts.append("=== PRIOR PROBLEM INVESTIGATIONS & INFERENCE NOTES ===")
        for file, data in inf_ctx.items():
            parts.append(f"Investigation File: {file}")
            preview = data.get("content", "")
            if preview:
                parts.append(preview[:1000])
                if len(preview) > 1000:
                    parts.append("... [Truncated Inference Context] ...")
        parts.append("")

    return "\n".join(parts)


def generate_rca_markdown_report(results: dict, query: str, log_data: dict) -> str:
    lines: List[str] = []
    lines.append("# LogSentry AI - Root Cause Analysis (RCA) Incident Report")
    lines.append(f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Environment:** {log_data.get('app', 'N/A')} | **Version:** {log_data.get('version', 'N/A')}")
    lines.append(f"**Query asked:** \"{query}\"")
    lines.append("---")

    lines.append("## AI Root Cause Analysis (AWS Bedrock)")
    lines.append(results.get("llm_explanation") or "*No AI explanation generated.*")
    lines.append("")

    lines.append("## Automated Analysis Summary")
    if results.get("automated_rca"):
        lines.append(results["automated_rca"])
    lines.append("")

    if results.get("time_correlation"):
        lines.append("### Time Correlation Details")
        lines.append(results["time_correlation"].get("message", ""))
        lines.append("")

    lines.append("## Diagnostics Context Summary")
    file_counts = log_data.get("file_counts", {})
    if file_counts:
        for k, v in file_counts.items():
            if v > 0:
                lines.append(f"- **{k.capitalize()} files parsed:** {v}")
    else:
        lines.append(f"- **Total files analyzed:** {log_data.get('file_count', 0)}")
    lines.append("")

    lines.append("---")
    lines.append("*Report generated by LogSentry AI | Production Support Portal*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class AnalysisPipeline:
    """Reusable, UI-free analysis pipeline.

    Heavy services (RAG engine, knowledge base, LLM client) are constructed once
    and reused across requests. Construct one instance at app startup.
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.config_path = config_path

        # Shared, thread-safe-enough read-only services
        self.log_reader = LogReader(config_path)
        self.rag_engine = RAGEngine(config_path)
        self.knowledge_base = KnowledgeBase(config_path=config_path)
        self.template_rca = TemplateRCA()
        self.llm = BedrockLLM()

    # -- LLM health ---------------------------------------------------------

    def llm_health(self) -> Dict[str, Any]:
        try:
            ok, err = self.llm.health_check()
            return {"ready": bool(ok), "error": err or "", "region": self.llm.region,
                    "model": self.llm.active_model_id}
        except Exception as e:
            return {"ready": False, "error": str(e), "region": getattr(self.llm, "region", ""),
                    "model": getattr(self.llm, "model_id", "")}

    # -- main entry ---------------------------------------------------------

    def analyze_directory(
        self,
        input_dir: str,
        query: str,
        *,
        confidential_terms: Optional[List[str]] = None,
        extra_context: str = "",
        app_label: str = NEUTRAL_APP,
        version_label: str = NEUTRAL_VERSION,
        progress_cb: Optional[ProgressCB] = None,
        knowledge_fn: Optional[Callable[[Dict[str, Any], Any], Optional[Dict[str, Any]]]] = None,
        high_assurance: bool = False,
        consensus_runs: int = 3,
    ) -> Dict[str, Any]:
        """Run the full pipeline over a directory of already-saved input files.

        knowledge_fn: optional callback (response, redactor) -> knowledge dict, used to
        augment the RCA with Confluence/Jira retrieval. Kept as an injected callable so
        this core module stays decoupled from the integrations layer.

        Returns a neutralized, JSON-serializable result bundle.
        """
        redactor = Redactor(RedactionConfig(confidential_terms=confidential_terms or []))

        def progress(stage: str, status: str, pct: float):
            if progress_cb:
                try:
                    progress_cb(stage, status, pct)
                except Exception:
                    pass

        started = time.time()
        progress("ingest", "running", 0.05)

        # 0) Adaptive plan — scan the source and derive memory caps + worker count
        #    scaled to the measured data size (dynamic consumption, no size assumption).
        profile: IngestionProfile = IngestionPlanner.scan(input_dir)

        # 1) Ingest + recursive extraction + parse (neutral metadata for NDA),
        #    bounded by the adaptive structured-entry cap.
        archive_processor = ArchiveProcessor()
        parse_results = archive_processor.process_directory(
            input_dir, self.log_reader.parser,
            NEUTRAL_ZONE, NEUTRAL_CLIENT, app_label, version_label,
            max_structured_entries=profile.max_structured_entries,
        )

        raw_text = "\n".join(parse_results.get("raw_logs_text", []))
        if len(raw_text) > profile.max_raw_chars:
            raw_text = raw_text[: profile.max_raw_chars] + "\n... [raw preview truncated by ingestion budget] ..."

        log_data: Dict[str, Any] = {
            "raw": raw_text,
            "structured": parse_results.get("structured_logs", []),
            "file_count": len(parse_results.get("all_files_metadata", [])),
            "app": app_label,
            "version": version_label,
            "source": "upload",
            "sql_context": parse_results.get("sql_context", {}),
            "pdf_context": parse_results.get("pdf_context", {}),
            "memory_context": parse_results.get("memory_context", {}),
            "inference_context": parse_results.get("inference_context", {}),
            "file_counts": parse_results.get("file_counts", {}),
            "all_files_metadata": parse_results.get("all_files_metadata", []),
        }
        progress("ingest", "done", 0.2)

        # 2) Phase-3 distributed agent orchestration (adaptive worker count).
        #    The legacy parser above extracts archives into its own scratch space and
        #    deletes them, so the agents (which walk the directory tree) would only see
        #    the .zip itself. Expand archives once into a temp dir the agents can scan,
        #    then pass BOTH the original dir (loose files) and the expanded content.
        progress("agents", "running", 0.25)
        extract_dir: Optional[str] = None
        agent_scan_dirs: List[str] = [input_dir]
        archives = self._find_archives(input_dir)
        if archives:
            extract_dir = tempfile.mkdtemp(prefix="logsentry_x_")
            xp = ArchiveProcessor(temp_dir=extract_dir)
            for arch in archives:
                try:
                    xp._extract_file(arch, extract_dir)
                except Exception:
                    pass
            if os.listdir(extract_dir):
                agent_scan_dirs.append(extract_dir)
                # Refine the plan (worker count + reported size) for the real,
                # uncompressed content now that we know it.
                ex = IngestionPlanner.scan(extract_dir)
                profile = IngestionPlanner.plan(
                    profile.total_bytes + ex.total_bytes,
                    profile.file_count + ex.file_count,
                    max(profile.largest_file_bytes, ex.largest_file_bytes),
                )
        try:
            agent_results_merged = self._run_agents(agent_scan_dirs, app_label, version_label, log_data, progress, profile.max_workers)
        finally:
            if extract_dir and os.path.isdir(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
        progress("agents", "done", 0.6)

        # 3) Core analysis (anomaly, time correlation, automated RCA, RAG/KB)
        progress("analysis", "running", 0.65)
        results = self._analyze(log_data, query)
        progress("analysis", "done", 0.8)

        # 4) LLM RCA on redacted context (optionally N-run consensus/"Venn" mode)
        progress("llm", "running", 0.82)
        consensus_block = None
        if high_assurance and agent_results_merged:
            text, consensus_block = self._consensus_rca(
                agent_results_merged, query, extra_context, redactor, consensus_runs, progress
            )
            results["llm_explanation"] = text
        else:
            results["llm_explanation"] = self._llm_rca(
                results, log_data, query, agent_results_merged, extra_context, redactor
            )
        progress("llm", "done", 0.95)

        # 5) Assemble neutralized, JSON-safe response
        response = self._build_response(results, log_data, query, agent_results_merged, redactor)
        response["meta"]["ingestion"] = profile.to_dict()
        if consensus_block:
            response["consensus"] = consensus_block

        # 6) Optional: retrieval-augmented reasoning over Confluence/Jira (or Demo data)
        if knowledge_fn is not None:
            progress("knowledge", "running", 0.96)
            try:
                knowledge = knowledge_fn(response, redactor)
                if knowledge is not None:
                    response["knowledge"] = knowledge
            except Exception as e:
                response["knowledge"] = {"available": False, "matches": [], "narrowed_analysis": "", "note": f"Retrieval failed: {e}"}
            progress("knowledge", "done", 0.99)

        response["meta"]["duration_ms"] = round((time.time() - started) * 1000, 1)
        progress("done", "done", 1.0)
        return response

    # -- stages -------------------------------------------------------------

    @staticmethod
    def _find_archives(root: str) -> List[str]:
        """List archive files anywhere under root (for pre-expansion before agents)."""
        exts = (".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".7z")
        found: List[str] = []
        for r, _d, files in os.walk(root):
            for f in files:
                if f.lower().endswith(exts):
                    found.append(os.path.join(r, f))
        return found

    def _run_agents(self, scan_dirs, app_label, version_label, log_data, progress, max_workers=4) -> Optional[dict]:
        try:
            if isinstance(scan_dirs, str):
                scan_dirs = [scan_dirs]
            roots = [d for d in scan_dirs if d and os.path.exists(d)]
            if not roots:
                return None

            classified: Dict[str, list] = defaultdict(list)
            seen: set = set()
            for scan_dir in roots:
                for root, _dirs, files in os.walk(scan_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        if fpath in seen:
                            continue
                        seen.add(fpath)
                        classified[FileClassifier.classify(fpath, fname)].append((fpath, fname))

            orch = AgentOrchestrator(max_workers=max_workers)
            for atype, cls in (
                (AGENT_APP_LOG, AppLogAgent), (AGENT_SQL, SQLAgent), (AGENT_PDF, PDFAgent),
                (AGENT_JVM, JVMAgent), (AGENT_PCAP, PCAPAgent), (AGENT_AUDIO, AudioAgent),
                (AGENT_SRE_NOTES, SRENotesAgent), (AGENT_CONFIG, ConfigAgent),
            ):
                orch.register_agent(atype, cls)

            def _agent_progress(agent_name, status, pct):
                progress(f"agent:{agent_name}", status, 0.25 + 0.35 * float(pct or 0))

            agent_results = orch.execute(
                dict(classified), progress_callback=_agent_progress,
                zone=NEUTRAL_ZONE, client=NEUTRAL_CLIENT,
                app=app_label, version=version_label,
            )
            merged = AgentResultMerger.merge(agent_results)

            # Enrich log_data (backward-compatible with legacy analysis)
            if merged.get("structured_logs") and not log_data.get("structured"):
                log_data["structured"] = merged["structured_logs"]
            for ctx_key in ("sql_context", "pdf_context", "memory_context",
                            "inference_context", "pcap_context", "audio_context", "config_context"):
                if merged.get(ctx_key):
                    existing = log_data.get(ctx_key, {})
                    existing.update(merged[ctx_key])
                    log_data[ctx_key] = existing
            if merged.get("all_files_metadata"):
                log_data.setdefault("all_files_metadata", []).extend(merged["all_files_metadata"])
            counts = log_data.get("file_counts", {})
            for k, v in merged.get("file_counts", {}).items():
                counts[k] = counts.get(k, 0) + v
            log_data["file_counts"] = counts
            return merged
        except Exception:
            log_data["_agent_error"] = traceback.format_exc(limit=3)
            return None

    def _analyze(self, log_data: dict, query: str) -> dict:
        structured = log_data.get("structured", [])
        total_errors = sum(1 for lg in structured if getattr(lg, "log_level", "") == "ERROR")
        unique_components = {getattr(lg, "component", None) for lg in structured if getattr(lg, "component", None)}

        results: Dict[str, Any] = {
            "log_stats": {
                "file_count": log_data.get("file_count", 0),
                "total_errors": total_errors,
                "unique_components": len(unique_components),
            },
            "error_lines": [str(lg) for lg in structured if getattr(lg, "log_level", "") == "ERROR"],
            "kb_solutions": [],
            "solutions": [],
        }

        # RAG + KB search
        raw_text = log_data.get("raw", "")
        exact = self.rag_engine.find_exact_matches(query, raw_text) if query else []
        results["exact_matches"] = exact
        results["similar_errors"] = (
            [] if exact else (self.rag_engine.find_similar_errors(query, raw_text)[:5] if query else [])
        )

        if query:
            kb_solutions = []
            for fix in self.knowledge_base.search_similar_issues(query, top_k=3):
                kb_solutions.append({
                    "error_type": fix["issue"],
                    "root_cause": fix["root_cause"],
                    "solution_steps": [s.strip() for s in fix["solution"].split(".") if s.strip()],
                    "confidence": fix["confidence"],
                })
            for component in list(unique_components)[:2]:
                kb_solutions.extend(self.knowledge_base.search_by_component(component) or [])
            results["kb_solutions"] = kb_solutions[:5]
            results["solutions"] = [{
                "error": s.get("error_type", "Known Issue"),
                "solution": "\n".join(s.get("solution_steps", [])),
                "confidence": s.get("confidence", "Medium"),
            } for s in results["kb_solutions"]]

        # template RCA, anomaly, time correlation, automated RCA
        results["template_rca"] = self.template_rca.generate(structured)
        anomaly = detect_error_anomaly(structured_logs=structured, threshold=5)
        results["anomaly"] = anomaly
        results["error_type"] = classify_error_type(
            "\n".join(results["error_lines"][:5]) or log_data.get("raw", "")
        )
        results["time_correlation"] = correlate_errors_by_time(
            structured_logs=structured, window_minutes=5, threshold=3
        )
        results["automated_rca"] = generate_automated_rca(
            anomaly_result=anomaly,
            time_corr_result=results["time_correlation"],
            total_errors=total_errors,
        )
        return results

    def _consensus_rca(self, agent_merged, query, extra_context, redactor, runs, progress):
        """High-assurance 'Venn' mode: N independent RCA runs, keep the agreed claims.

        Returns (consensus_markdown, consensus_meta_dict). Reduces hallucination by
        surfacing only claims multiple runs agree on and flagging single-run outliers.
        """
        from backend.core.consensus import run_consensus

        summary = AgentResultMerger.build_llm_prompt_context(agent_merged)
        summary = redactor.redact(summary)
        if extra_context:
            summary += "\n\n=== ADDITIONAL USER CONTEXT (redacted) ===\n" + redactor.redact(extra_context)
        q = redactor.redact(query)
        embed = self.knowledge_base.vector_store.embedding_service.encode

        counter = {"i": 0}

        def gen(temp: float) -> str:
            counter["i"] += 1
            progress("consensus", "running", 0.82 + 0.1 * (counter["i"] / max(runs, 1)))
            try:
                return self.llm.generate_from_agent_results(summary, query=q, temperature=temp)
            except Exception:
                return ""

        try:
            cres = run_consensus(gen, embed, n=runs)
            return cres.consensus_text, cres.to_dict()
        except Exception as e:
            # On any failure, degrade to a single standard RCA
            single = self.llm.generate_from_agent_results(summary, query=q)
            return single, {"runs": 0, "agreement_score": 0.0, "error": str(e),
                            "consensus_claims": [], "flagged_claims": []}

    def _llm_rca(self, results, log_data, query, agent_merged, extra_context, redactor) -> str:
        """Generate the RCA via Bedrock using REDACTED context only (NDA-safe)."""
        try:
            if not results.get("anomaly", {}).get("anomaly_detected") and not agent_merged:
                return "No anomaly detected across the supplied diagnostics; no AI RCA generated."

            if agent_merged:
                summary = AgentResultMerger.build_llm_prompt_context(agent_merged)
                summary = redactor.redact(summary)
                if extra_context:
                    summary += "\n\n=== ADDITIONAL USER CONTEXT (redacted) ===\n" + redactor.redact(extra_context)
                return self.llm.generate_from_agent_results(summary, query=redactor.redact(query))

            # Legacy pathway — redact both the sample and the diagnostic context
            sample = "\n".join(results.get("error_lines", [])[:5]) or "ERROR: Unknown issue"
            arch_ctx = {
                "sql_context": log_data.get("sql_context", {}),
                "pdf_context": log_data.get("pdf_context", {}),
                "memory_context": log_data.get("memory_context", {}),
                "inference_context": log_data.get("inference_context", {}),
            }
            ctx_text = redactor.redact(format_archive_context_for_prompt(arch_ctx))
            if extra_context:
                ctx_text += "\n\n=== ADDITIONAL USER CONTEXT (redacted) ===\n" + redactor.redact(extra_context)
            prompt = self._legacy_prompt(redactor.redact(sample), ctx_text)
            return self.llm.generate(prompt, max_tokens=700, temperature=0.2)
        except Exception as e:
            return f"[LLM RCA unavailable] {e}"

    @staticmethod
    def _legacy_prompt(log_text: str, extra_context: str) -> str:
        prompt = f"""You are an expert production support / SRE engineer analyzing logs and diagnostics for an enterprise trading communications environment.

Analyze the evidence below and generate a precise Root Cause Analysis (RCA).
Return the answer in this exact structure:

### Root Cause
### Impact Level
### Suggested Fix
### Confidence Level
### Evidence From Diagnostics

Rules: do not invent components, timestamps, or errors. Be concise and actionable.

Log Events:
{log_text}
"""
        if extra_context:
            prompt += f"\nAdditional Diagnostics Context:\n{extra_context}\n"
        return prompt

    def _build_response(self, results, log_data, query, agent_merged, redactor) -> Dict[str, Any]:
        """Neutralize and serialize the full result set for the API boundary."""
        structured = log_data.get("structured", [])
        # Redact free-text error lines and previews before they leave the boundary
        error_lines = redactor.redact_lines(results.get("error_lines", [])[:200])
        exact = redactor.redact_lines(results.get("exact_matches", [])[:100])
        similar = redactor.redact_lines(results.get("similar_errors", [])[:100])

        structured_sample = [serialize_log_entry(lg) for lg in structured[:500]]
        for entry in structured_sample:
            entry["raw"] = redactor.redact(entry.get("raw", ""))
            entry["message"] = redactor.redact(entry.get("message", ""))

        report_md = generate_rca_markdown_report(
            {**results, "llm_explanation": results.get("llm_explanation", "")}, query, log_data
        )

        response = {
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "query": query,
                "app": log_data.get("app"),
                "version": log_data.get("version"),
                "file_count": log_data.get("file_count", 0),
                "overall_severity": (agent_merged or {}).get("overall_severity", "INFO"),
                "redaction_summary": redactor.summary,
            },
            "rca": {
                "llm_explanation": results.get("llm_explanation", ""),
                "automated_rca": results.get("automated_rca", ""),
                "error_type": results.get("error_type", "Other"),
                "template_rca": to_jsonable(results.get("template_rca")),
                "report_markdown": report_md,
            },
            "stats": to_jsonable(results.get("log_stats", {})),
            "anomaly": redactor.redact_mapping(to_jsonable(results.get("anomaly", {}))),
            "time_correlation": redactor.redact_mapping(to_jsonable(results.get("time_correlation", {}))),
            "solutions": redactor.redact_mapping(to_jsonable(results.get("solutions", []))),
            "kb_solutions": redactor.redact_mapping(to_jsonable(results.get("kb_solutions", []))),
            "evidence": {
                "error_lines": error_lines,
                "exact_matches": exact,
                "similar_errors": similar,
            },
            "diagnostics": {
                "file_counts": to_jsonable(log_data.get("file_counts", {})),
                "sql_context": redactor.redact_mapping(to_jsonable(log_data.get("sql_context", {}))),
                "pdf_context": redactor.redact_mapping(to_jsonable(log_data.get("pdf_context", {}))),
                "memory_context": redactor.redact_mapping(to_jsonable(log_data.get("memory_context", {}))),
                "inference_context": redactor.redact_mapping(to_jsonable(log_data.get("inference_context", {}))),
                "pcap_context": redactor.redact_mapping(to_jsonable(log_data.get("pcap_context", {}))),
                "audio_context": redactor.redact_mapping(to_jsonable(log_data.get("audio_context", {}))),
                "config_context": redactor.redact_mapping(to_jsonable(log_data.get("config_context", {}))),
            },
            "agents": {
                "summaries": redactor.redact_mapping((agent_merged or {}).get("agent_summaries", {})),
                "timings": to_jsonable((agent_merged or {}).get("agent_timings", {})),
                "total_findings": (agent_merged or {}).get("total_findings", 0),
            },
            "logs_sample": structured_sample,
        }
        return response
