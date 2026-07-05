# src/services/agent_framework.py
"""
Enterprise-scale distributed agent framework for LogSentry AI.

Architecture:
  - FileClassifier: routes files to the correct agent by extension + content signature
  - BaseAgent: abstract interface every specialized agent implements
  - AgentResult: standardized output dataclass
  - AgentOrchestrator: parallel execution via ProcessPoolExecutor (parallel-by-type, serial-within-type)
  - AgentResultMerger: combines all AgentResult objects into a unified diagnostic context
"""

import os
import re
import time
import traceback
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Standardized output from every agent."""
    agent_name: str
    file_count: int = 0
    files_processed: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    severity: str = "INFO"          # INFO | WARN | ERROR | CRITICAL
    summary: str = ""               # One-paragraph human-readable summary
    errors: List[str] = field(default_factory=list)  # Processing errors
    duration_ms: float = 0.0

    # Structured context buckets (backward-compatible with existing pipeline)
    structured_logs: List[Any] = field(default_factory=list)
    raw_logs_text: List[str] = field(default_factory=list)
    sql_context: Dict[str, Any] = field(default_factory=dict)
    pdf_context: Dict[str, Any] = field(default_factory=dict)
    memory_context: Dict[str, Any] = field(default_factory=dict)
    inference_context: Dict[str, Any] = field(default_factory=dict)
    pcap_context: Dict[str, Any] = field(default_factory=dict)
    audio_context: Dict[str, Any] = field(default_factory=dict)
    config_context: Dict[str, Any] = field(default_factory=dict)
    all_files_metadata: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File Classification
# ---------------------------------------------------------------------------

# Agent type constants
AGENT_APP_LOG = "app_log"
AGENT_SQL = "sql"
AGENT_PDF = "pdf"
AGENT_JVM = "jvm"
AGENT_PCAP = "pcap"
AGENT_AUDIO = "audio"
AGENT_SRE_NOTES = "sre_notes"
AGENT_CONFIG = "config"
AGENT_ARCHIVE = "archive"       # Internal — handled by extractor, not an agent
AGENT_UNKNOWN = "unknown"


class FileClassifier:
    """Routes files to the correct specialized agent based on extension and content signatures."""

    # Extension-based routing (fast path)
    EXTENSION_MAP = {
        ".sql": AGENT_SQL,
        ".pdf": AGENT_PDF,
        ".pcap": AGENT_PCAP,
        ".pcapng": AGENT_PCAP,
        ".wav": AGENT_AUDIO,
        ".mp3": AGENT_AUDIO,
        ".ogg": AGENT_AUDIO,
        ".flac": AGENT_AUDIO,
        ".properties": AGENT_CONFIG,
        ".conf": AGENT_CONFIG,
        ".cfg": AGENT_CONFIG,
        ".ini": AGENT_CONFIG,
        ".xml": AGENT_CONFIG,
        ".hprof": AGENT_JVM,
    }

    # Archive extensions — not routed to agents, handled by extractor
    ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tgz", ".gz", ".tar.gz", ".bz2", ".7z"}

    # Content signature patterns for text files (checked if extension doesn't match)
    CONTENT_SIGNATURES = [
        # JVM diagnostics (check before generic logs)
        (AGENT_JVM, [
            r"java\.lang\.Thread\.State:",
            r"Full thread dump",
            r"prio=\d+",
            r"Heap Object Histogram",
            r"Max Heap:",
            r"Heap committed:",
            r"Heap used:",
            r"Memory max size",
            r"GC pause",
            r"Full GC",
            r"Evacuation Pause",
            r"G1 Evacuation",
            r"jr_print",
        ]),
        # SRE / Incident notes (check before generic logs)
        (AGENT_SRE_NOTES, [
            r"\bPBI\d+",
            r"Problem Investigation",
            r"Root Cause Analysis Notes",
            r"\bincident\b.*\breport\b",
            r"\bremediation\b",
            r"Inference",
        ]),
        # PCAP-AM (proprietary IPC wrapper, text metadata)
        (AGENT_PCAP, [
            r"PCAP-AM",
            r"pcap.*audio.*monitor",
        ]),
        # Audio CDR (text-based call detail records)
        (AGENT_AUDIO, [
            r"Call Detail Record",
            r"\bCDR\b",
            r"call_duration",
            r"codec.*G\.\d{3}",
        ]),
    ]

    @classmethod
    def classify(cls, filepath: str, filename: str) -> str:
        """Classify a file and return the agent type constant."""
        filename_lower = filename.lower()

        # 1. Check archive extensions
        for ext in cls.ARCHIVE_EXTENSIONS:
            if filename_lower.endswith(ext):
                return AGENT_ARCHIVE

        # 2. Check direct extension map
        _, ext = os.path.splitext(filename_lower)
        if ext in cls.EXTENSION_MAP:
            return cls.EXTENSION_MAP[ext]

        # 3. YAML files — could be config
        if ext in (".yaml", ".yml"):
            return AGENT_CONFIG

        # 4. For text files, read a content sample and check signatures
        if cls._is_text_file(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    sample = f.read(8000)
            except Exception:
                return AGENT_APP_LOG  # Default fallback

            for agent_type, patterns in cls.CONTENT_SIGNATURES:
                for pattern in patterns:
                    if re.search(pattern, sample, re.IGNORECASE):
                        return agent_type

            # Default text file → app log
            return AGENT_APP_LOG

        # 5. Binary file we don't recognize
        return AGENT_UNKNOWN

    @staticmethod
    def _is_text_file(filepath: str) -> bool:
        """Quick check if a file is text-readable."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="strict") as f:
                f.read(1024)
            return True
        except (UnicodeDecodeError, Exception):
            # Try latin-1 as fallback
            try:
                with open(filepath, "r", encoding="latin-1") as f:
                    chunk = f.read(1024)
                # Check if it looks like text (no null bytes)
                return "\x00" not in chunk
            except Exception:
                return False


# ---------------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base class for all specialized agents."""

    AGENT_NAME: str = "base"
    STREAMING_CHUNK_SIZE: int = 10 * 1024 * 1024  # 10 MB

    @abstractmethod
    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        """
        Analyze a single file and return a dict of findings.
        Must be implemented by each specialized agent.
        """
        pass

    def analyze_batch(self, file_list: List[Tuple[str, str]], **kwargs) -> AgentResult:
        """
        Process a batch of files serially (within this agent type).
        Returns a single AgentResult combining all files.
        """
        result = AgentResult(agent_name=self.AGENT_NAME)
        start_time = time.time()

        for filepath, filename in file_list:
            try:
                file_result = self.analyze(filepath, filename, **kwargs)
                result.files_processed.append(filename)
                result.file_count += 1

                # Merge file-level results into the batch result
                self._merge_file_result(result, file_result, filename)

            except Exception as e:
                result.errors.append(f"Error processing {filename}: {str(e)}")

        result.duration_ms = (time.time() - start_time) * 1000
        result.summary = self._generate_summary(result)
        result.severity = self._compute_severity(result)
        return result

    def _merge_file_result(self, batch_result: AgentResult, file_result: Dict, filename: str):
        """Merge a single file's analysis into the batch result. Override in subclasses for custom merging."""
        if "findings" in file_result:
            batch_result.findings.extend(file_result["findings"])
        if "evidence" in file_result:
            batch_result.evidence.extend(file_result["evidence"])
        if "metrics" in file_result:
            batch_result.metrics[filename] = file_result["metrics"]
        if "metadata" in file_result:
            batch_result.all_files_metadata.append(file_result["metadata"])

    def _generate_summary(self, result: AgentResult) -> str:
        """Generate a human-readable summary. Override in subclasses."""
        return f"{self.AGENT_NAME}: processed {result.file_count} files, found {len(result.findings)} findings."

    def _compute_severity(self, result: AgentResult) -> str:
        """Compute overall severity from findings."""
        severities = [f.get("severity", "INFO") for f in result.findings]
        if "CRITICAL" in severities:
            return "CRITICAL"
        if "ERROR" in severities:
            return "ERROR"
        if "WARN" in severities:
            return "WARN"
        return "INFO"

    @staticmethod
    def format_size(bytes_val: int) -> str:
        """Format byte count to human-readable string."""
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def safe_file_size(filepath: str) -> int:
        """Get file size safely."""
        try:
            return os.path.getsize(filepath)
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# Agent Orchestrator
# ---------------------------------------------------------------------------

def _run_agent_batch(agent_class, file_list, kwargs):
    """
    Top-level function for ProcessPoolExecutor (must be picklable).
    Instantiates the agent and runs analyze_batch.
    """
    agent = agent_class()
    return agent.analyze_batch(file_list, **kwargs)


class AgentOrchestrator:
    """
    Manages parallel execution of specialized agents.
    Groups files by type → spawns one agent per type in parallel.
    Each agent processes its files serially with streaming I/O.
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._agent_registry: Dict[str, type] = {}

    def register_agent(self, agent_type: str, agent_class: type):
        """Register a specialized agent class for a file type."""
        self._agent_registry[agent_type] = agent_class

    def execute(
        self,
        classified_files: Dict[str, List[Tuple[str, str]]],
        progress_callback=None,
        **kwargs
    ) -> Dict[str, AgentResult]:
        """
        Execute all agents in parallel.

        Args:
            classified_files: {agent_type: [(filepath, filename), ...]}
            progress_callback: Optional callable(agent_name, status, progress_pct)
            **kwargs: Passed to each agent's analyze_batch

        Returns:
            {agent_type: AgentResult}
        """
        results: Dict[str, AgentResult] = {}
        tasks_to_run = {}

        # Filter to only types that have registered agents and files
        for agent_type, file_list in classified_files.items():
            if not file_list:
                continue
            if agent_type == AGENT_ARCHIVE:
                continue  # Archives are handled by extractor, not agents
            if agent_type == AGENT_UNKNOWN:
                continue  # Skip unknown files
            if agent_type not in self._agent_registry:
                continue
            tasks_to_run[agent_type] = file_list

        if not tasks_to_run:
            return results

        total_tasks = len(tasks_to_run)
        completed = 0

        # Use ProcessPoolExecutor for true parallelism across file types
        # Fall back to sequential if max_workers is 1 or only 1 task
        if self.max_workers <= 1 or total_tasks <= 1:
            for agent_type, file_list in tasks_to_run.items():
                if progress_callback:
                    progress_callback(agent_type, "running", completed / total_tasks)
                agent_class = self._agent_registry[agent_type]
                agent = agent_class()
                results[agent_type] = agent.analyze_batch(file_list, **kwargs)
                completed += 1
                if progress_callback:
                    progress_callback(agent_type, "done", completed / total_tasks)
        else:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, total_tasks)) as executor:
                future_to_type = {}
                for agent_type, file_list in tasks_to_run.items():
                    if progress_callback:
                        progress_callback(agent_type, "submitted", completed / total_tasks)
                    agent_class = self._agent_registry[agent_type]
                    future = executor.submit(
                        _run_agent_batch, agent_class, file_list, kwargs
                    )
                    future_to_type[future] = agent_type

                for future in as_completed(future_to_type):
                    agent_type = future_to_type[future]
                    try:
                        results[agent_type] = future.result()
                    except Exception as e:
                        results[agent_type] = AgentResult(
                            agent_name=agent_type,
                            errors=[f"Agent execution failed: {str(e)}\n{traceback.format_exc()}"],
                            severity="ERROR"
                        )
                    completed += 1
                    if progress_callback:
                        progress_callback(agent_type, "done", completed / total_tasks)

        return results


# ---------------------------------------------------------------------------
# Agent Result Merger
# ---------------------------------------------------------------------------

class AgentResultMerger:
    """Combines all AgentResult objects into a unified diagnostic context dict."""

    @staticmethod
    def merge(agent_results: Dict[str, AgentResult]) -> Dict[str, Any]:
        """
        Merge all agent results into a single unified context dict.
        This output is backward-compatible with the existing app.py pipeline.
        """
        merged = {
            "structured_logs": [],
            "raw_logs_text": [],
            "sql_context": {},
            "pdf_context": {},
            "memory_context": {},
            "inference_context": {},
            "pcap_context": {},
            "audio_context": {},
            "config_context": {},
            "file_counts": {
                "logs": 0,
                "sql": 0,
                "pdf": 0,
                "memory": 0,
                "inference": 0,
                "pcap": 0,
                "audio": 0,
                "config": 0,
            },
            "all_files_metadata": [],
            "agent_summaries": {},
            "agent_timings": {},
            "overall_severity": "INFO",
            "total_findings": 0,
            "all_evidence": [],
        }

        severity_order = {"INFO": 0, "WARN": 1, "ERROR": 2, "CRITICAL": 3}
        max_severity = 0

        for agent_type, result in agent_results.items():
            # Collect timing and summaries
            merged["agent_summaries"][agent_type] = result.summary
            merged["agent_timings"][agent_type] = result.duration_ms
            merged["total_findings"] += len(result.findings)
            merged["all_evidence"].extend(result.evidence)

            # Severity tracking
            sev_val = severity_order.get(result.severity, 0)
            if sev_val > max_severity:
                max_severity = sev_val

            # Merge structured context buckets
            merged["structured_logs"].extend(result.structured_logs)
            merged["raw_logs_text"].extend(result.raw_logs_text)
            merged["sql_context"].update(result.sql_context)
            merged["pdf_context"].update(result.pdf_context)
            merged["memory_context"].update(result.memory_context)
            merged["inference_context"].update(result.inference_context)
            merged["pcap_context"].update(result.pcap_context)
            merged["audio_context"].update(result.audio_context)
            merged["config_context"].update(result.config_context)
            merged["all_files_metadata"].extend(result.all_files_metadata)

            # File counts
            if agent_type == AGENT_APP_LOG:
                merged["file_counts"]["logs"] += result.file_count
            elif agent_type == AGENT_SQL:
                merged["file_counts"]["sql"] += result.file_count
            elif agent_type == AGENT_PDF:
                merged["file_counts"]["pdf"] += result.file_count
            elif agent_type == AGENT_JVM:
                merged["file_counts"]["memory"] += result.file_count
            elif agent_type == AGENT_SRE_NOTES:
                merged["file_counts"]["inference"] += result.file_count
            elif agent_type == AGENT_PCAP:
                merged["file_counts"]["pcap"] += result.file_count
            elif agent_type == AGENT_AUDIO:
                merged["file_counts"]["audio"] += result.file_count
            elif agent_type == AGENT_CONFIG:
                merged["file_counts"]["config"] += result.file_count

        # Resolve severity
        for sev_name, sev_val in severity_order.items():
            if sev_val == max_severity:
                merged["overall_severity"] = sev_name
                break

        return merged

    @staticmethod
    def build_llm_prompt_context(merged: Dict[str, Any], max_chars: int = 4000) -> str:
        """
        Build a compressed, token-efficient summary string for the LLM prompt.
        Designed to stay under ~700 tokens regardless of input bundle size.
        """
        parts = []

        # Agent summaries
        for agent_type, summary in merged.get("agent_summaries", {}).items():
            if summary:
                parts.append(f"[{agent_type.upper()}] {summary}")

        # Top evidence items
        evidence = merged.get("all_evidence", [])
        if evidence:
            parts.append("--- KEY EVIDENCE ---")
            for ev in evidence[:10]:
                parts.append(f"  • {ev[:200]}")

        # Overall severity
        parts.append(f"OVERALL SEVERITY: {merged.get('overall_severity', 'INFO')}")
        parts.append(f"TOTAL FINDINGS: {merged.get('total_findings', 0)}")

        result = "\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[Context truncated for token efficiency]"
        return result
