# src/utils/parser.py

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class StructuredLog:
    timestamp: Optional[str]
    log_level: str
    message: str
    component: Optional[str]
    error_code: Optional[str]
    zone: str
    client: str
    app: str
    version: str

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "log_level": self.log_level,
            "message": self.message,
            "component": self.component,
            "error_code": self.error_code,
            "zone": self.zone,
            "client": self.client,
            "app": self.app,
            "version": self.version,
        }


class LogParser:
    KNOWN_COMPONENTS = [
        "database", "sip", "api", "auth", "network", "replication",
        "unigydb", "ccm", "console", "unigy", "heartbeat", "scheduler",
        "jvm", "gc", "heap", "session", "gateway", "proxy", "cluster"
    ]

    def parse_line(self, line: str, zone: str, client: str, app: str, version: str) -> Optional[StructuredLog]:
        line = line.strip()
        if not line:
            return None

        line_lower = line.lower()

        # Log level detection — order matters (check WARN before ERROR to avoid double-match)
        if "error" in line_lower or "exception" in line_lower or "fatal" in line_lower:
            log_level = "ERROR"
        elif "warn" in line_lower:
            log_level = "WARN"
        elif "info" in line_lower:
            log_level = "INFO"
        elif "debug" in line_lower:
            log_level = "DEBUG"
        elif "trace" in line_lower:
            log_level = "TRACE"
        else:
            log_level = "INFO"

        # Extract timestamp — try ISO-8601 first, then date-only
        timestamp = None
        ts_match = re.search(
            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)",
            line
        )
        if ts_match:
            timestamp = ts_match.group(1)
        else:
            ts_date = re.match(r"(\d{4}-\d{2}-\d{2})", line)
            if ts_date:
                timestamp = ts_date.group(1)

        # Extract error code
        error_code_match = re.search(r"\b(E_[A-Z_]+|ERR-\d+|[A-Z]{2,6}-\d{3,6})\b", line)
        error_code = error_code_match.group(1) if error_code_match else None

        # Extract component
        component = None
        for comp in self.KNOWN_COMPONENTS:
            if comp in line_lower:
                component = comp.upper()
                break

        return StructuredLog(
            timestamp=timestamp,
            log_level=log_level,
            message=line,
            component=component,
            error_code=error_code,
            zone=zone,
            client=client,
            app=app,
            version=version,
        )
