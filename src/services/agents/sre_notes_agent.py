# src/services/agents/sre_notes_agent.py
"""
SRENotesAgent: Parser for SRE/PBI inference notes, incident reports, and remediation documents.
Extracts PBI numbers, incident IDs, root cause patterns, and prior fixes.
"""

import os
import re
from typing import Dict, List, Any

from src.services.agent_framework import BaseAgent


class SRENotesAgent(BaseAgent):
    AGENT_NAME = "sre_notes"

    # Incident/PBI number patterns
    ID_PATTERNS = [
        re.compile(r"\b(PBI\d{4,10})\b", re.IGNORECASE),
        re.compile(r"\b(INC\d{4,12})\b", re.IGNORECASE),
        re.compile(r"\b(CR\d{4,10})\b", re.IGNORECASE),
        re.compile(r"\b(CHG\d{4,10})\b", re.IGNORECASE),
        re.compile(r"\b(TASK\d{4,10})\b", re.IGNORECASE),
        re.compile(r"\b(SR\d{4,10})\b", re.IGNORECASE),
    ]

    # Root cause keywords
    ROOT_CAUSE_KEYWORDS = [
        "root cause", "rca", "caused by", "due to", "because of",
        "identified as", "traced to", "result of", "contributing factor",
        "failure mode", "fault",
    ]

    # Remediation keywords
    REMEDIATION_KEYWORDS = [
        "remediation", "fix", "resolution", "workaround", "mitigation",
        "action taken", "corrective action", "patch", "upgrade",
        "restart", "reconfigure", "failover", "rollback",
    ]

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        findings = []
        incident_ids = set()
        root_causes = []
        remediations = []
        total_lines = 0

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to read {filename}: {e}"}],
                "metadata": {"filename": filename, "file_type": "SRE Notes", "size": self.format_size(size_bytes), "highlights": "Read error"},
                "inference_data": {"filename": filename, "error": str(e)},
            }

        total_lines = content.count("\n") + 1
        content_lower = content.lower()

        # Extract incident / PBI IDs
        for pattern in self.ID_PATTERNS:
            for match in pattern.finditer(content):
                incident_ids.add(match.group(1).upper())

        # Extract root cause statements (capture the surrounding context)
        for kw in self.ROOT_CAUSE_KEYWORDS:
            for match in re.finditer(re.escape(kw), content_lower):
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 200)
                snippet = content[start:end].strip().replace("\n", " ")
                if snippet and len(root_causes) < 10:
                    root_causes.append(snippet[:300])

        # Extract remediation statements
        for kw in self.REMEDIATION_KEYWORDS:
            for match in re.finditer(re.escape(kw), content_lower):
                start = max(0, match.start() - 30)
                end = min(len(content), match.end() + 200)
                snippet = content[start:end].strip().replace("\n", " ")
                if snippet and len(remediations) < 10:
                    remediations.append(snippet[:300])

        # Build findings
        if incident_ids:
            findings.append({
                "severity": "INFO",
                "message": f"Incident references found: {', '.join(sorted(incident_ids))}",
            })
        if root_causes:
            findings.append({
                "severity": "INFO",
                "message": f"{len(root_causes)} root cause statement(s) identified in {filename}",
                "details": root_causes[:3],
            })
        if remediations:
            findings.append({
                "severity": "INFO",
                "message": f"{len(remediations)} remediation action(s) documented in {filename}",
                "details": remediations[:3],
            })

        ids_str = ", ".join(sorted(incident_ids)) if incident_ids else "None"
        highlights = f"Incident IDs: {ids_str} | RCAs: {len(root_causes)} | Remediations: {len(remediations)}"

        inference_data = {
            "filename": filename,
            "content": content[:5000],
            "incident_ids": sorted(incident_ids),
            "root_causes": root_causes,
            "remediations": remediations,
            "total_lines": total_lines,
        }

        return {
            "findings": findings,
            "evidence": root_causes[:3],
            "metrics": {"incident_ids": len(incident_ids), "root_causes": len(root_causes), "remediations": len(remediations)},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "SRE Notes", "size": self.format_size(size_bytes), "highlights": highlights},
            "inference_data": inference_data,
        }

    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "inference_data" in file_result:
            batch_result.inference_context[filename] = file_result["inference_data"]

    def _generate_summary(self, result):
        all_ids = set()
        total_rcas = 0
        for m in result.metrics.values():
            if isinstance(m, dict):
                total_rcas += m.get("root_causes", 0)
        for fn, ctx in result.inference_context.items():
            all_ids.update(ctx.get("incident_ids", []))
        ids_str = f" Refs: {', '.join(sorted(all_ids))}." if all_ids else ""
        return f"Parsed {result.file_count} SRE/incident files. {total_rcas} root cause statements extracted.{ids_str}"
