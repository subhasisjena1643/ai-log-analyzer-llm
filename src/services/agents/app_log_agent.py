# src/services/agents/app_log_agent.py
"""
AppLogAgent: Streaming parser for application log files.
Handles .log, .txt, messages, engine logs, operator commands, SAR metrics.
Streams files line-by-line to handle multi-GB logs without memory exhaustion.
"""

import os
import re
from typing import Dict, List, Any, Tuple

from src.services.agent_framework import BaseAgent


class AppLogAgent(BaseAgent):
    AGENT_NAME = "app_log"

    # Known log-level keywords
    LOG_LEVELS = ["FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "TRACE"]

    # Timestamp patterns (ISO-8601, syslog, custom)
    TS_PATTERNS = [
        re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"),
        re.compile(r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"),  # syslog: Mar  6 18:05:12
        re.compile(r"(\d{4}-\d{2}-\d{2})"),                       # date only
    ]

    # Known IPC component keywords
    KNOWN_COMPONENTS = [
        "database", "sip", "api", "auth", "network", "replication",
        "unigydb", "ccm", "console", "unigy", "heartbeat", "scheduler",
        "jvm", "gc", "heap", "session", "gateway", "proxy", "cluster",
        "engine", "replica", "operator", "sar", "kernel",
    ]

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        findings = []
        error_lines = []
        warn_lines = []
        log_level_counts = {}
        total_lines = 0
        components_seen = set()
        error_codes = []
        timestamps_seen = []
        preview_lines = []
        max_preview = 500

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    stripped = line.strip()
                    if not stripped:
                        continue

                    if total_lines <= max_preview:
                        preview_lines.append(line)

                    line_lower = stripped.lower()

                    # Detect log level
                    level = self._detect_level(stripped)
                    log_level_counts[level] = log_level_counts.get(level, 0) + 1

                    if level == "ERROR" or level == "FATAL":
                        if len(error_lines) < 50:
                            error_lines.append(stripped[:200])
                    elif level == "WARN" or level == "WARNING":
                        if len(warn_lines) < 20:
                            warn_lines.append(stripped[:200])

                    # Extract error codes
                    ec_match = re.search(r"\b(E_[A-Z_]+|ERR-\d+|[A-Z]{2,6}-\d{3,6})\b", stripped)
                    if ec_match and len(error_codes) < 20:
                        error_codes.append(ec_match.group(1))

                    # Extract components
                    for comp in self.KNOWN_COMPONENTS:
                        if comp in line_lower:
                            components_seen.add(comp.upper())
                            break

                    # Extract timestamp (first few only for timeline)
                    if len(timestamps_seen) < 100:
                        ts = self._extract_timestamp(stripped)
                        if ts:
                            timestamps_seen.append(ts)

        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to read {filename}: {e}"}],
                "metadata": {
                    "filename": filename,
                    "file_type": "App Log",
                    "size": self.format_size(size_bytes),
                    "highlights": f"Read error: {e}",
                },
            }

        # Build findings
        if error_lines:
            findings.append({
                "severity": "ERROR",
                "message": f"{len(error_lines)} error lines detected in {filename}",
                "sample_errors": error_lines[:5],
            })
        if warn_lines:
            findings.append({
                "severity": "WARN",
                "message": f"{len(warn_lines)} warning lines in {filename}",
            })

        highlights = f"{total_lines} lines | Errors: {log_level_counts.get('ERROR', 0) + log_level_counts.get('FATAL', 0)} | Warnings: {log_level_counts.get('WARN', 0) + log_level_counts.get('WARNING', 0)}"

        # Build structured log entries for backward compatibility
        structured = self._build_structured_logs(
            filepath, filename, kwargs.get("zone", ""), kwargs.get("client", ""),
            kwargs.get("app", ""), kwargs.get("version", "")
        )

        return {
            "findings": findings,
            "evidence": error_lines[:5],
            "metrics": {
                "total_lines": total_lines,
                "log_level_counts": log_level_counts,
                "components": list(components_seen),
                "error_codes": list(set(error_codes)),
            },
            "metadata": {
                "filename": filename,
                "relative_path": filename,
                "file_type": "App Log",
                "size": self.format_size(size_bytes),
                "highlights": highlights,
            },
            "structured_logs": structured,
            "raw_preview": "".join(preview_lines),
        }

    def _merge_file_result(self, batch_result, file_result, filename):
        """Custom merge: accumulate structured logs and raw text."""
        super()._merge_file_result(batch_result, file_result, filename)

        if "structured_logs" in file_result:
            batch_result.structured_logs.extend(file_result["structured_logs"])

        if "raw_preview" in file_result:
            batch_result.raw_logs_text.append(f"=== File: {filename} ===\n{file_result['raw_preview']}")

    def _generate_summary(self, result):
        total_errors = sum(
            f.get("metrics", {}).get("log_level_counts", {}).get("ERROR", 0)
            + f.get("metrics", {}).get("log_level_counts", {}).get("FATAL", 0)
            for f in [result.metrics.get(fn, {}) for fn in result.files_processed]
            if isinstance(f, dict)
        )
        return f"Parsed {result.file_count} log files. {total_errors} error entries detected across all files."

    def _detect_level(self, line: str) -> str:
        upper = line.upper()
        if "FATAL" in upper:
            return "FATAL"
        if "ERROR" in upper or "EXCEPTION" in upper:
            return "ERROR"
        if "WARN" in upper:
            return "WARN"
        if "DEBUG" in upper:
            return "DEBUG"
        if "TRACE" in upper:
            return "TRACE"
        return "INFO"

    def _extract_timestamp(self, line: str) -> str:
        for pat in self.TS_PATTERNS:
            m = pat.search(line)
            if m:
                return m.group(1)
        return ""

    def _build_structured_logs(self, filepath, filename, zone, client, app, version):
        """Build StructuredLog-compatible entries for backward compat with app.py."""
        # Import here to avoid circular imports at module level
        try:
            from src.utils.parser import LogParser
            parser = LogParser()
        except ImportError:
            return []

        logs = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip():
                        parsed = parser.parse_line(line, zone, client, app, version)
                        if parsed:
                            logs.append(parsed)
        except Exception:
            pass
        return logs
