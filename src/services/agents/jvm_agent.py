# src/services/agents/jvm_agent.py
"""
JVMAgent: Comprehensive analyzer for all JVM diagnostic files.
Handles: heap diagnostics, memory usage, object summaries, thread dumps, GC logs, .hprof (future).
"""

import os
import re
from typing import Dict, List, Any, Optional

from src.services.agent_framework import BaseAgent


class JVMAgent(BaseAgent):
    AGENT_NAME = "jvm"

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        filename_lower = filename.lower()

        # Route to specialized sub-parser based on content
        if filename_lower.endswith(".hprof"):
            return self._analyze_hprof(filepath, filename, size_bytes)

        # Read content sample to determine sub-type
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                sample = f.read(8000)
        except Exception as e:
            return self._error_result(filename, size_bytes, str(e))

        sample_lower = sample.lower()

        # Thread dump
        if "java.lang.thread.state" in sample_lower or "full thread dump" in sample_lower or "prio=" in sample_lower:
            return self._analyze_thread_dump(filepath, filename, size_bytes)

        # Object histogram / summary
        if "heap object histogram" in sample_lower or ("instances" in sample_lower and "bytes" in sample_lower and "class" in sample_lower):
            return self._analyze_object_summary(filepath, filename, size_bytes)

        # GC log
        if "gc pause" in sample_lower or "full gc" in sample_lower or "evacuation pause" in sample_lower:
            return self._analyze_gc_log(filepath, filename, size_bytes)

        # Heap / memory usage (default JVM diagnostic)
        return self._analyze_heap_memory(filepath, filename, size_bytes)

    # -----------------------------------------------------------------------
    # Thread Dump Analysis
    # -----------------------------------------------------------------------
    def _analyze_thread_dump(self, filepath, filename, size_bytes):
        thread_states = {"RUNNABLE": 0, "WAITING": 0, "TIMED_WAITING": 0, "BLOCKED": 0}
        deadlock_detected = False
        blocked_threads = []
        total_threads = 0
        findings = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                current_thread_name = ""
                for line in f:
                    stripped = line.strip()
                    line_lower = stripped.lower()

                    # Thread name line
                    thread_name_match = re.match(r'"([^"]+)"', stripped)
                    if thread_name_match:
                        current_thread_name = thread_name_match.group(1)
                        total_threads += 1

                    # Thread state
                    if "java.lang.thread.state:" in line_lower:
                        for state in thread_states:
                            if state.lower() in line_lower:
                                thread_states[state] += 1
                                if state == "BLOCKED" and current_thread_name:
                                    blocked_threads.append(current_thread_name)
                                break

                    # Summary-style counts: "Runnable: 45"
                    for state in thread_states:
                        match = re.search(rf"\b{state.lower()}\s*[:=]\s*(\d+)", line_lower)
                        if match:
                            thread_states[state] = max(thread_states[state], int(match.group(1)))

                    # Deadlock detection
                    if "deadlock" in line_lower:
                        deadlock_detected = True

        except Exception as e:
            return self._error_result(filename, size_bytes, str(e))

        if thread_states["BLOCKED"] > 0:
            findings.append({
                "severity": "ERROR",
                "message": f"{thread_states['BLOCKED']} BLOCKED threads detected in {filename}",
                "details": blocked_threads[:10],
            })
        if deadlock_detected:
            findings.append({
                "severity": "CRITICAL",
                "message": f"DEADLOCK detected in thread dump {filename}",
            })

        states_str = ", ".join(f"{k}: {v}" for k, v in thread_states.items() if v > 0)
        highlights = f"Threads: {total_threads} | States: {states_str}" + (" | ⚠️ DEADLOCK" if deadlock_detected else "")

        mem_data = {
            "filename": filename,
            "thread_states": thread_states if any(v > 0 for v in thread_states.values()) else None,
            "total_threads": total_threads,
            "blocked_threads": blocked_threads,
            "deadlock_detected": deadlock_detected,
        }

        return {
            "findings": findings,
            "evidence": [f"BLOCKED threads: {', '.join(blocked_threads[:5])}"] if blocked_threads else [],
            "metrics": {"thread_states": thread_states, "total_threads": total_threads, "deadlock": deadlock_detected},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "JVM Thread Dump", "size": self.format_size(size_bytes), "highlights": highlights},
            "memory_data": mem_data,
        }

    # -----------------------------------------------------------------------
    # Heap / Memory Usage Analysis
    # -----------------------------------------------------------------------
    def _analyze_heap_memory(self, filepath, filename, size_bytes):
        heap_max_mb = None
        heap_used_mb = None
        heap_committed_mb = None
        findings = []
        # Also capture thread state summaries if present
        thread_states = {"RUNNABLE": 0, "WAITING": 0, "TIMED_WAITING": 0, "BLOCKED": 0}

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_lower = line.lower()

                    if "non-heap" in line_lower or "nonheap" in line_lower:
                        continue

                    if "max" in line_lower and any(k in line_lower for k in ["heap", "memory", "xmx", "size"]):
                        val = self._extract_mb(line)
                        if val:
                            heap_max_mb = val

                    if "committed" in line_lower and any(k in line_lower for k in ["heap", "memory"]):
                        val = self._extract_mb(line)
                        if val:
                            heap_committed_mb = val

                    if "used" in line_lower and any(k in line_lower for k in ["heap", "memory", "usage", "size"]):
                        val = self._extract_mb(line)
                        if val:
                            heap_used_mb = val

                    # Thread state summaries
                    for state in thread_states:
                        match = re.search(rf"\b{state.lower()}\s*[:=]\s*(\d+)", line_lower)
                        if match:
                            thread_states[state] = max(thread_states[state], int(match.group(1)))

        except Exception as e:
            return self._error_result(filename, size_bytes, str(e))

        # Saturation check
        if heap_used_mb and heap_max_mb and heap_max_mb > 0:
            pct = (heap_used_mb / heap_max_mb) * 100
            if pct >= 90:
                findings.append({
                    "severity": "CRITICAL",
                    "message": f"JVM heap saturation at {pct:.1f}% ({heap_used_mb:.0f}/{heap_max_mb:.0f} MB) in {filename}",
                })
            elif pct >= 75:
                findings.append({
                    "severity": "WARN",
                    "message": f"JVM heap usage elevated at {pct:.1f}% in {filename}",
                })

        highlights = f"Heap Used: {heap_used_mb or 'N/A'} MB / Max: {heap_max_mb or 'N/A'} MB"

        mem_data = {
            "filename": filename,
            "heap_max_mb": heap_max_mb,
            "heap_committed_mb": heap_committed_mb or heap_max_mb,
            "heap_used_mb": heap_used_mb,
            "thread_states": thread_states if any(v > 0 for v in thread_states.values()) else None,
        }

        return {
            "findings": findings,
            "evidence": [f"Heap: {heap_used_mb} MB / {heap_max_mb} MB"] if heap_used_mb else [],
            "metrics": {"heap_used_mb": heap_used_mb, "heap_max_mb": heap_max_mb},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "JVM Memory Dump", "size": self.format_size(size_bytes), "highlights": highlights},
            "memory_data": mem_data,
        }

    # -----------------------------------------------------------------------
    # Object Summary / Histogram Analysis
    # -----------------------------------------------------------------------
    def _analyze_object_summary(self, filepath, filename, size_bytes):
        """Parse jr_print_object_summary files — heap object histogram."""
        top_objects = []
        total_instances = 0
        total_bytes_val = 0
        findings = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # Typical format: "  num   #instances  #bytes  class name"
                    # or: "   1:  123456  12345678  java.lang.String"
                    match = re.match(r"\s*\d+:\s+(\d+)\s+(\d+)\s+(.+)", line.strip())
                    if match:
                        instances = int(match.group(1))
                        byte_count = int(match.group(2))
                        class_name = match.group(3).strip()
                        total_instances += instances
                        total_bytes_val += byte_count
                        if len(top_objects) < 20:
                            top_objects.append({
                                "class": class_name,
                                "instances": instances,
                                "bytes": byte_count,
                                "size_str": self.format_size(byte_count),
                            })
        except Exception as e:
            return self._error_result(filename, size_bytes, str(e))

        if top_objects:
            top_class = top_objects[0]
            findings.append({
                "severity": "INFO",
                "message": f"Top heap object: {top_class['class']} ({top_class['instances']} instances, {top_class['size_str']})",
            })

        highlights = f"Object Histogram: {total_instances} instances, {self.format_size(total_bytes_val)} total"

        mem_data = {
            "filename": filename,
            "top_objects": top_objects,
            "total_instances": total_instances,
            "total_bytes": total_bytes_val,
        }

        return {
            "findings": findings,
            "evidence": [f"Top object: {top_objects[0]['class']} ({top_objects[0]['instances']} instances)"] if top_objects else [],
            "metrics": {"total_instances": total_instances, "total_bytes": total_bytes_val, "top_classes": len(top_objects)},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "JVM Heap Histogram", "size": self.format_size(size_bytes), "highlights": highlights},
            "memory_data": mem_data,
        }

    # -----------------------------------------------------------------------
    # GC Log Analysis
    # -----------------------------------------------------------------------
    def _analyze_gc_log(self, filepath, filename, size_bytes):
        gc_pauses = []
        full_gc_count = 0
        max_pause_ms = 0.0
        total_events = 0
        findings = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_lower = line.lower()
                    if "gc" in line_lower and any(k in line_lower for k in ["pause", "ms", "sec", "duration"]):
                        total_events += 1
                        if len(gc_pauses) < 20:
                            gc_pauses.append(line.strip()[:200])

                        # Extract pause duration
                        ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", line)
                        if ms_match:
                            pause = float(ms_match.group(1))
                            max_pause_ms = max(max_pause_ms, pause)

                        if "full gc" in line_lower:
                            full_gc_count += 1

        except Exception as e:
            return self._error_result(filename, size_bytes, str(e))

        if max_pause_ms > 500:
            findings.append({
                "severity": "ERROR",
                "message": f"High GC pause time: {max_pause_ms:.0f}ms in {filename}",
            })
        elif max_pause_ms > 200:
            findings.append({
                "severity": "WARN",
                "message": f"Elevated GC pause time: {max_pause_ms:.0f}ms in {filename}",
            })
        if full_gc_count > 0:
            findings.append({
                "severity": "WARN",
                "message": f"{full_gc_count} Full GC events detected in {filename} — indicates memory pressure",
            })

        highlights = f"GC Events: {total_events} | Full GC: {full_gc_count} | Max Pause: {max_pause_ms:.0f}ms"

        mem_data = {
            "filename": filename,
            "gc_pauses": gc_pauses,
            "full_gc_count": full_gc_count,
            "max_pause_ms": max_pause_ms,
            "total_events": total_events,
        }

        return {
            "findings": findings,
            "evidence": gc_pauses[:3],
            "metrics": {"total_events": total_events, "full_gc_count": full_gc_count, "max_pause_ms": max_pause_ms},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "GC Log", "size": self.format_size(size_bytes), "highlights": highlights},
            "memory_data": mem_data,
        }

    # -----------------------------------------------------------------------
    # .hprof Binary Heap Dump (Future — Eclipse MAT integration)
    # -----------------------------------------------------------------------
    def _analyze_hprof(self, filepath, filename, size_bytes):
        """Placeholder for binary .hprof heap dump analysis via Eclipse MAT headless."""
        highlights = f"Binary heap dump ({self.format_size(size_bytes)}) — requires Eclipse MAT for deep analysis"
        findings = [{
            "severity": "INFO",
            "message": f"Binary .hprof heap dump detected: {filename} ({self.format_size(size_bytes)}). "
                       "Deep analysis requires Eclipse MAT headless mode (not installed). "
                       "Basic metadata extracted.",
        }]

        mem_data = {
            "filename": filename,
            "type": "hprof_binary",
            "size_bytes": size_bytes,
            "note": "Eclipse MAT headless integration pending. File registered for future analysis.",
        }

        return {
            "findings": findings,
            "evidence": [],
            "metrics": {"size_bytes": size_bytes, "type": "hprof_binary"},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "JVM Heap Dump (.hprof)", "size": self.format_size(size_bytes), "highlights": highlights},
            "memory_data": mem_data,
        }

    # -----------------------------------------------------------------------
    # Merge + Helpers
    # -----------------------------------------------------------------------
    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "memory_data" in file_result:
            batch_result.memory_context[filename] = file_result["memory_data"]

    def _generate_summary(self, result):
        parts = [f"Parsed {result.file_count} JVM diagnostic files."]
        # Aggregate key metrics
        for fn, metrics in result.metrics.items():
            if isinstance(metrics, dict):
                if metrics.get("heap_used_mb"):
                    parts.append(f"Heap: {metrics['heap_used_mb']:.0f}/{metrics.get('heap_max_mb', 'N/A')} MB.")
                if metrics.get("deadlock"):
                    parts.append("DEADLOCK detected!")
                if metrics.get("full_gc_count"):
                    parts.append(f"Full GC events: {metrics['full_gc_count']}.")
        return " ".join(parts)

    def _extract_mb(self, text: str) -> Optional[float]:
        """Extract a numeric value from text and convert to MB."""
        # Match value + unit
        match = re.search(r"(\d+(?:\.\d+)?)\s*(mb|m|gb|g|kb|k|bytes|b)\b", text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            unit = match.group(2).lower()
            if unit in ("gb", "g"):
                return val * 1024
            elif unit in ("kb", "k"):
                return val / 1024
            elif unit in ("bytes", "b"):
                return val / (1024 * 1024)
            return val  # MB

        # Plain number after colon/equals (assume bytes)
        match_num = re.search(r"[:=]\s*(\d+(?:\.\d+)?)", text)
        if match_num:
            val = float(match_num.group(1))
            if val > 1_000_000:  # Likely bytes
                return val / (1024 * 1024)
            return val
        return None

    def _error_result(self, filename, size_bytes, error_msg):
        return {
            "findings": [{"severity": "ERROR", "message": f"Failed to parse {filename}: {error_msg}"}],
            "metadata": {"filename": filename, "file_type": "JVM Diagnostic", "size": self.format_size(size_bytes), "highlights": f"Error: {error_msg[:80]}"},
        }
