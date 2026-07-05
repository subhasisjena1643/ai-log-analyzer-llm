# src/services/agents/pdf_agent.py
"""
PDFAgent: Analyzer for TAC Automation HealthCheck PDFs.
Supports multi-date trending across multiple healthcheck reports.
"""

import os
import re
from typing import Dict, List, Any

from src.services.agent_framework import BaseAgent


class PDFAgent(BaseAgent):
    AGENT_NAME = "pdf"

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        findings = []

        try:
            import pypdf
        except ImportError:
            return {
                "findings": [{"severity": "WARN", "message": "pypdf not installed — cannot parse PDF files"}],
                "metadata": {"filename": filename, "file_type": "PDF Report", "size": self.format_size(size_bytes), "highlights": "pypdf missing"},
            }

        try:
            text_pages = []
            with open(filepath, "rb") as f:
                reader = pypdf.PdfReader(f)
                total_pages = len(reader.pages)
                for page in reader.pages:
                    text_pages.append(page.extract_text() or "")

            full_text = "\n".join(text_pages)
            lines = full_text.splitlines()

            failures = []
            warnings = []
            passes = []
            date_detected = None

            for line in lines:
                line_lower = line.lower().strip()

                # Detect date in healthcheck title
                date_match = re.search(r"(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})", line)
                if date_match and not date_detected:
                    date_detected = date_match.group(1)

                # Classify checkpoints
                if any(kw in line_lower for kw in ["fail", "failed", "critical", "error", "unreachable", "offline"]):
                    failures.append(line.strip()[:200])
                elif any(kw in line_lower for kw in ["warn", "warning", "degraded", "restarting"]):
                    warnings.append(line.strip()[:200])
                elif any(kw in line_lower for kw in ["pass", "ok", "[ok]", "success"]):
                    passes.append(line.strip()[:200])

            # Build findings
            if failures:
                findings.append({
                    "severity": "ERROR",
                    "message": f"{len(failures)} failed healthcheck(s) in {filename}",
                    "details": failures[:5],
                    "date": date_detected,
                })
            if warnings:
                findings.append({
                    "severity": "WARN",
                    "message": f"{len(warnings)} degraded/warning checkpoint(s) in {filename}",
                    "details": warnings[:5],
                    "date": date_detected,
                })

            unique_failures = list(set(failures))[:15]
            unique_warnings = list(set(warnings))[:15]

            highlights = f"Pages: {total_pages} | Failures: {len(unique_failures)} | Warnings: {len(unique_warnings)}"
            if date_detected:
                highlights = f"Date: {date_detected} | " + highlights

            pdf_data = {
                "filename": filename,
                "total_pages": total_pages,
                "failures": unique_failures,
                "warnings": unique_warnings,
                "passes": list(set(passes))[:10],
                "date": date_detected,
                "extracted_text": full_text[:4000],
            }

            return {
                "findings": findings,
                "evidence": unique_failures[:3],
                "metrics": {"pages": total_pages, "failures": len(unique_failures), "warnings": len(unique_warnings), "date": date_detected},
                "metadata": {"filename": filename, "relative_path": filename, "file_type": "PDF Report", "size": self.format_size(size_bytes), "highlights": highlights},
                "pdf_data": pdf_data,
            }

        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to parse PDF {filename}: {e}"}],
                "metadata": {"filename": filename, "file_type": "PDF Report", "size": self.format_size(size_bytes), "highlights": f"Parse error"},
            }

    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "pdf_data" in file_result:
            batch_result.pdf_context[filename] = file_result["pdf_data"]

    def _generate_summary(self, result):
        total_failures = sum(m.get("failures", 0) for m in result.metrics.values() if isinstance(m, dict))
        dates = [m.get("date") for m in result.metrics.values() if isinstance(m, dict) and m.get("date")]
        date_str = f" spanning dates {', '.join(dates)}" if dates else ""
        return f"Parsed {result.file_count} PDF healthcheck reports{date_str}. {total_failures} total failures detected."
