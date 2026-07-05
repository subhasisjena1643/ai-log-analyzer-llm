# src/services/agents/sql_agent.py
"""
SQLAgent: Analyzer for SQL database schema dumps and query logs.
Handles .sql files from IPC Unigy database exports.
"""

import os
import re
from typing import Dict, List, Any

from src.services.agent_framework import BaseAgent


class SQLAgent(BaseAgent):
    AGENT_NAME = "sql"

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        tables = []
        errors = []
        queries_count = 0
        constraints = []
        deadlocks = []
        total_lines = 0
        preview_lines = []
        max_preview = 100
        findings = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    if total_lines <= max_preview:
                        preview_lines.append(line)

                    stripped = line.strip()
                    line_lower = stripped.lower()

                    # Detect table creation
                    table_match = re.search(
                        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_`\".]+)",
                        line, re.IGNORECASE
                    )
                    if table_match:
                        tables.append(table_match.group(1).replace("`", "").replace('"', ""))

                    # Detect constraints
                    if "foreign key" in line_lower:
                        if len(constraints) < 20:
                            constraints.append(stripped[:200])

                    # Detect errors
                    if any(k in line_lower for k in ["error", "fail", "rollback", "deadlock", "exception", "violation"]):
                        if len(errors) < 30:
                            errors.append(stripped[:200])

                    # Detect deadlocks specifically
                    if "deadlock" in line_lower:
                        if len(deadlocks) < 10:
                            deadlocks.append(stripped[:200])

                    # Count queries
                    if stripped.endswith(";"):
                        queries_count += 1

        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to parse SQL {filename}: {e}"}],
                "metadata": {"filename": filename, "file_type": "SQL Schema/Dump", "size": self.format_size(size_bytes), "highlights": f"Read error"},
            }

        # Build findings
        if errors:
            findings.append({
                "severity": "ERROR",
                "message": f"{len(errors)} SQL errors/violations detected in {filename}",
                "details": errors[:5],
            })
        if deadlocks:
            findings.append({
                "severity": "CRITICAL",
                "message": f"{len(deadlocks)} deadlock events detected",
                "details": deadlocks[:3],
            })
        if constraints:
            findings.append({
                "severity": "WARN",
                "message": f"{len(constraints)} foreign key constraints found — verify referential integrity",
            })

        unique_tables = list(set(tables))
        highlights = f"Queries: {queries_count} | Tables: {len(unique_tables)} | Errors: {len(errors)}"

        sql_data = {
            "filename": filename,
            "tables_found": unique_tables,
            "errors_found": errors,
            "constraints": constraints,
            "deadlocks": deadlocks,
            "queries_count": queries_count,
            "total_lines": total_lines,
            "preview": "".join(preview_lines),
        }

        return {
            "findings": findings,
            "evidence": errors[:5],
            "metrics": {"tables": len(unique_tables), "errors": len(errors), "queries": queries_count},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "SQL Schema/Dump", "size": self.format_size(size_bytes), "highlights": highlights},
            "sql_data": sql_data,
        }

    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "sql_data" in file_result:
            batch_result.sql_context[filename] = file_result["sql_data"]

    def _generate_summary(self, result):
        total_errors = sum(m.get("errors", 0) for m in result.metrics.values() if isinstance(m, dict))
        total_tables = sum(m.get("tables", 0) for m in result.metrics.values() if isinstance(m, dict))
        return f"Parsed {result.file_count} SQL files. {total_tables} tables, {total_errors} errors/violations detected."
