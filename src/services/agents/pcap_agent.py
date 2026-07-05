# src/services/agents/pcap_agent.py
"""
PCAPAgent: Network packet capture analyzer.
Handles .pcap, .pcapng files and PCAP-AM (IPC proprietary wrappers).

Phase 1: Native binary header parser — packet counts, protocol distribution, duration.
Phase 2: Optional tshark integration for deep SIP/RTP analysis.
"""

import os
import re
import struct
import shutil
from typing import Dict, List, Any, Optional

from src.services.agent_framework import BaseAgent


class PCAPAgent(BaseAgent):
    AGENT_NAME = "pcap"

    # Standard PCAP magic numbers
    PCAP_MAGIC_LE = 0xA1B2C3D4
    PCAP_MAGIC_BE = 0xD4C3B2A1
    PCAPNG_MAGIC = 0x0A0D0D0A

    # Well-known protocol numbers
    PROTOCOL_MAP = {
        1: "ICMP", 6: "TCP", 17: "UDP",
    }

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        filename_lower = filename.lower()

        # Check if it's a text-based PCAP-AM metadata file
        if self._is_text_file(filepath):
            return self._analyze_pcap_am_text(filepath, filename, size_bytes)

        # Try native binary PCAP parsing
        result = self._analyze_pcap_binary(filepath, filename, size_bytes)

        # If tshark is available, enhance with deep analysis
        tshark_path = self._find_tshark()
        if tshark_path and size_bytes < 500 * 1024 * 1024:  # Only for files < 500MB
            tshark_result = self._analyze_with_tshark(tshark_path, filepath, filename)
            if tshark_result:
                result["findings"].extend(tshark_result.get("findings", []))
                result.get("pcap_data", {}).update(tshark_result.get("tshark_data", {}))

        return result

    def _analyze_pcap_binary(self, filepath, filename, size_bytes):
        """Native PCAP header parser — no external dependencies."""
        findings = []
        packet_count = 0
        protocols = {}
        min_ts = None
        max_ts = None
        src_ips = set()
        dst_ips = set()

        try:
            with open(filepath, "rb") as f:
                # Read global header (24 bytes)
                header = f.read(24)
                if len(header) < 24:
                    return self._unsupported_result(filename, size_bytes, "File too small for PCAP header")

                magic = struct.unpack("<I", header[:4])[0]
                if magic == self.PCAP_MAGIC_LE:
                    endian = "<"
                elif magic == self.PCAP_MAGIC_BE:
                    endian = ">"
                elif magic == self.PCAPNG_MAGIC:
                    return self._pcapng_result(filename, size_bytes)
                else:
                    return self._unsupported_result(filename, size_bytes, "Unknown PCAP format or proprietary IPC wrapper")

                # Parse packet records (limited to first 10000 packets for performance)
                max_packets = 10000
                while packet_count < max_packets:
                    pkt_header = f.read(16)
                    if len(pkt_header) < 16:
                        break

                    ts_sec, ts_usec, incl_len, orig_len = struct.unpack(f"{endian}IIII", pkt_header)
                    packet_count += 1

                    # Track timestamps
                    if min_ts is None or ts_sec < min_ts:
                        min_ts = ts_sec
                    if max_ts is None or ts_sec > max_ts:
                        max_ts = ts_sec

                    # Read packet data (just enough for Ethernet + IP header)
                    pkt_data = f.read(min(incl_len, 54))
                    remaining = incl_len - len(pkt_data)
                    if remaining > 0:
                        f.seek(remaining, 1)  # Skip rest of packet

                    # Parse Ethernet header (14 bytes) + IP header
                    if len(pkt_data) >= 34:
                        # IP protocol byte at offset 23
                        ip_proto = pkt_data[23]
                        proto_name = self.PROTOCOL_MAP.get(ip_proto, f"Proto-{ip_proto}")
                        protocols[proto_name] = protocols.get(proto_name, 0) + 1

                        # Source and dest IP at bytes 26-29 and 30-33
                        if len(pkt_data) >= 34:
                            src_ip = ".".join(str(b) for b in pkt_data[26:30])
                            dst_ip = ".".join(str(b) for b in pkt_data[30:34])
                            src_ips.add(src_ip)
                            dst_ips.add(dst_ip)

                # Estimate total if we hit max
                if packet_count >= max_packets:
                    current_pos = f.tell()
                    f.seek(0, 2)
                    total_size = f.tell()
                    est_total = int(packet_count * (total_size / current_pos)) if current_pos > 0 else packet_count
                else:
                    est_total = packet_count

        except Exception as e:
            return self._unsupported_result(filename, size_bytes, str(e))

        # Build findings
        duration_sec = (max_ts - min_ts) if min_ts and max_ts else 0

        if protocols.get("UDP", 0) > protocols.get("TCP", 0) * 2:
            findings.append({
                "severity": "INFO",
                "message": f"High UDP traffic ratio in {filename} — likely contains RTP/voice streams",
            })

        proto_str = ", ".join(f"{k}: {v}" for k, v in sorted(protocols.items(), key=lambda x: -x[1])[:5])
        highlights = f"Packets: {est_total:,} | Duration: {duration_sec}s | Protocols: {proto_str}"

        pcap_data = {
            "filename": filename,
            "packet_count": est_total,
            "packets_sampled": packet_count,
            "duration_seconds": duration_sec,
            "protocols": protocols,
            "unique_sources": len(src_ips),
            "unique_destinations": len(dst_ips),
            "top_sources": list(src_ips)[:10],
            "top_destinations": list(dst_ips)[:10],
        }

        return {
            "findings": findings,
            "evidence": [f"PCAP: {est_total:,} packets, {proto_str}"],
            "metrics": {"packets": est_total, "duration_sec": duration_sec, "protocols": protocols},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "PCAP Capture", "size": self.format_size(size_bytes), "highlights": highlights},
            "pcap_data": pcap_data,
        }

    def _analyze_pcap_am_text(self, filepath, filename, size_bytes):
        """Parse text-based PCAP-AM metadata files (IPC proprietary)."""
        findings = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(10000)
        except Exception as e:
            return self._unsupported_result(filename, size_bytes, str(e))

        highlights = f"PCAP-AM metadata file ({self.format_size(size_bytes)})"
        pcap_data = {
            "filename": filename,
            "type": "pcap_am_metadata",
            "content_preview": content[:2000],
        }

        return {
            "findings": findings,
            "evidence": [],
            "metrics": {},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "PCAP-AM Metadata", "size": self.format_size(size_bytes), "highlights": highlights},
            "pcap_data": pcap_data,
        }

    def _analyze_with_tshark(self, tshark_path, filepath, filename):
        """Optional deep analysis via tshark CLI."""
        import subprocess
        try:
            # Get protocol hierarchy
            result = subprocess.run(
                [tshark_path, "-r", filepath, "-q", "-z", "io,phs"],
                capture_output=True, text=True, timeout=60
            )
            tshark_data = {"protocol_hierarchy": result.stdout[:2000]}

            # Try to get SIP statistics
            sip_result = subprocess.run(
                [tshark_path, "-r", filepath, "-q", "-z", "sip,stat"],
                capture_output=True, text=True, timeout=30
            )
            if sip_result.stdout:
                tshark_data["sip_statistics"] = sip_result.stdout[:2000]

            return {"findings": [], "tshark_data": tshark_data}
        except Exception:
            return None

    def _find_tshark(self) -> Optional[str]:
        """Auto-detect tshark installation."""
        return shutil.which("tshark")

    def _pcapng_result(self, filename, size_bytes):
        return {
            "findings": [{"severity": "INFO", "message": f"PCAPNG format detected in {filename} — use tshark for detailed analysis"}],
            "evidence": [],
            "metrics": {"format": "pcapng"},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "PCAP-NG Capture", "size": self.format_size(size_bytes), "highlights": f"PCAPNG format ({self.format_size(size_bytes)})"},
            "pcap_data": {"filename": filename, "format": "pcapng", "note": "Install tshark for deep analysis"},
        }

    def _unsupported_result(self, filename, size_bytes, reason):
        return {
            "findings": [{"severity": "WARN", "message": f"Could not parse {filename}: {reason}"}],
            "evidence": [],
            "metrics": {},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "PCAP (Unsupported Format)", "size": self.format_size(size_bytes), "highlights": reason[:100]},
            "pcap_data": {"filename": filename, "error": reason},
        }

    def _is_text_file(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8", errors="strict") as f:
                chunk = f.read(512)
            return "\x00" not in chunk
        except Exception:
            return False

    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "pcap_data" in file_result:
            batch_result.pcap_context[filename] = file_result["pcap_data"]

    def _generate_summary(self, result):
        total_packets = sum(m.get("packets", 0) for m in result.metrics.values() if isinstance(m, dict))
        return f"Analyzed {result.file_count} PCAP files. {total_packets:,} total packets captured."
