# src/services/agents/config_agent.py
"""
ConfigAgent: Analyzer for configuration files.
Handles .properties, .conf, .cfg, .yaml, .yml, .xml, .ini files.
Detects misconfigurations, pool sizes, heap settings, port bindings.
"""

import os
import re
from typing import Dict, List, Any

from src.services.agent_framework import BaseAgent


class ConfigAgent(BaseAgent):
    AGENT_NAME = "config"

    # Known configuration parameters to flag
    CRITICAL_PARAMS = {
        "pool.size": "Connection pool size",
        "pool-size": "Connection pool size",
        "maxpoolsize": "Max pool size",
        "max_connections": "Max connections",
        "maxconnections": "Max connections",
        "max.pool.size": "Max pool size",
        "xmx": "JVM max heap",
        "xms": "JVM initial heap",
        "maxheapsize": "Max heap size",
        "heap.size": "Heap size",
        "timeout": "Timeout value",
        "connection.timeout": "Connection timeout",
        "read.timeout": "Read timeout",
        "session.timeout": "Session timeout",
        "max.retries": "Max retries",
        "maxretries": "Max retries",
        "replication.factor": "Replication factor",
        "port": "Port binding",
        "bind.address": "Bind address",
        "listen.address": "Listen address",
        "ssl.enabled": "SSL/TLS enabled",
        "tls.enabled": "TLS enabled",
        "log.level": "Log level",
        "loglevel": "Log level",
        "max.threads": "Max threads",
        "thread.pool.size": "Thread pool size",
    }

    # Misconfiguration patterns
    MISCONFIG_PATTERNS = [
        (r"(?:pool[_.-]?size|maxpool\w*)\s*[=:]\s*(\d+)", "pool_size",
         lambda v: int(v) >= 100, "WARN", "Very large connection pool size ({value}) may cause resource exhaustion"),
        (r"(?:pool[_.-]?size|maxpool\w*)\s*[=:]\s*(\d+)", "pool_size_low",
         lambda v: int(v) <= 5, "WARN", "Very small connection pool size ({value}) may cause bottlenecks"),
        (r"-Xmx(\d+[mgMG])", "xmx",
         lambda v: _parse_mem_mb(v) >= 8192, "INFO", "Large JVM heap configured: -Xmx{value}"),
        (r"timeout\s*[=:]\s*(\d+)", "timeout",
         lambda v: int(v) <= 5, "WARN", "Very short timeout ({value}) may cause premature failures"),
        (r"(?:ssl|tls)[._-]?enabled\s*[=:]\s*(false|no|0)", "ssl_disabled",
         lambda v: True, "WARN", "SSL/TLS is DISABLED — potential security risk"),
        (r"log[._-]?level\s*[=:]\s*(DEBUG|TRACE)", "debug_logging",
         lambda v: True, "INFO", "Debug/Trace logging enabled — may impact performance in production"),
    ]

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        filename_lower = filename.lower()
        findings = []
        config_params = {}
        misconfigs = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000)  # Config files are usually small
        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to read {filename}: {e}"}],
                "metadata": {"filename": filename, "file_type": "Config File", "size": self.format_size(size_bytes), "highlights": "Read error"},
                "config_data": {"filename": filename, "error": str(e)},
            }

        # Parse key-value pairs
        if filename_lower.endswith((".yaml", ".yml")):
            config_params = self._parse_yaml_flat(content)
        elif filename_lower.endswith(".xml"):
            config_params = self._parse_xml_flat(content)
        elif filename_lower.endswith((".properties", ".conf", ".cfg", ".ini")):
            config_params = self._parse_properties(content)
        else:
            config_params = self._parse_properties(content)

        # Check for critical parameters
        critical_found = {}
        for key, value in config_params.items():
            key_lower = key.lower().replace("_", ".").replace("-", ".")
            for param_key, param_desc in self.CRITICAL_PARAMS.items():
                if param_key in key_lower:
                    critical_found[param_desc] = {"key": key, "value": value}
                    break

        # Check for misconfiguration patterns
        for pattern, name, check_fn, severity, msg_template in self.MISCONFIG_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                value = match.group(1)
                try:
                    if check_fn(value):
                        msg = msg_template.format(value=value)
                        misconfigs.append({"name": name, "value": value, "message": msg, "severity": severity})
                        findings.append({"severity": severity, "message": f"[{filename}] {msg}"})
                except (ValueError, TypeError):
                    pass

        # Build highlights
        param_count = len(config_params)
        critical_count = len(critical_found)
        misconfig_count = len(misconfigs)
        highlights = f"Config: {param_count} params | Critical: {critical_count} | Issues: {misconfig_count}"

        config_data = {
            "filename": filename,
            "format": os.path.splitext(filename)[1].lstrip("."),
            "total_params": param_count,
            "critical_params": critical_found,
            "misconfigurations": misconfigs,
            "all_params": dict(list(config_params.items())[:50]),  # Limit stored params
        }

        return {
            "findings": findings,
            "evidence": [m["message"] for m in misconfigs[:3]],
            "metrics": {"params": param_count, "critical": critical_count, "misconfigs": misconfig_count},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "Config File", "size": self.format_size(size_bytes), "highlights": highlights},
            "config_data": config_data,
        }

    # -----------------------------------------------------------------------
    # Parsers
    # -----------------------------------------------------------------------
    def _parse_properties(self, content: str) -> Dict[str, str]:
        """Parse Java .properties / .conf / .ini key-value files."""
        params = {}
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "!", "//", ";")):
                continue

            # Section headers in .ini files
            if stripped.startswith("[") and stripped.endswith("]"):
                continue

            # Key = Value or Key: Value
            match = re.match(r"^([^=:]+?)\s*[=:]\s*(.*)$", stripped)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                # Remove inline comments
                for comment_char in ("#", "//"):
                    if comment_char in value:
                        value = value[:value.index(comment_char)].strip()
                params[key] = value
        return params

    def _parse_yaml_flat(self, content: str) -> Dict[str, str]:
        """Flat parse YAML-like content (no library required)."""
        params = {}
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^([^:]+):\s*(.+)$", stripped)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                if value.startswith(('"', "'")):
                    value = value.strip("'\"")
                params[key] = value
        return params

    def _parse_xml_flat(self, content: str) -> Dict[str, str]:
        """Extract key-value pairs from XML attributes and simple elements."""
        params = {}
        # Simple element values: <key>value</key>
        for match in re.finditer(r"<(\w+)>([^<]+)</\1>", content):
            params[match.group(1)] = match.group(2).strip()
        # Attributes: name="value" or key="value"
        for match in re.finditer(r'(\w+)=["\']([^"\']+)["\']', content):
            params[match.group(1)] = match.group(2)
        return params

    # -----------------------------------------------------------------------
    # Merge
    # -----------------------------------------------------------------------
    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "config_data" in file_result:
            batch_result.config_context[filename] = file_result["config_data"]

    def _generate_summary(self, result):
        total_misconfigs = sum(m.get("misconfigs", 0) for m in result.metrics.values() if isinstance(m, dict))
        return f"Analyzed {result.file_count} config files. {total_misconfigs} potential misconfigurations detected."


def _parse_mem_mb(val_str: str) -> int:
    """Parse memory value like '4096m' or '8g' to MB."""
    val_str = val_str.strip().lower()
    if val_str.endswith("g"):
        return int(val_str[:-1]) * 1024
    elif val_str.endswith("m"):
        return int(val_str[:-1])
    elif val_str.endswith("k"):
        return int(val_str[:-1]) // 1024
    return int(val_str)
