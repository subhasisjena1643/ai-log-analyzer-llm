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


# SIP is ASCII text carried over UDP/TCP. These line-anchored patterns let us extract
# call signalling directly from the raw capture bytes without tshark or full packet
# reassembly — works for classic pcap, pcapng, and text PCAP-AM wrappers alike.
_SIP_METHODS = "INVITE|ACK|BYE|CANCEL|REGISTER|OPTIONS|SUBSCRIBE|NOTIFY|INFO|PRACK|UPDATE|REFER|MESSAGE"
_SIP_REQ = re.compile(rf"\b({_SIP_METHODS})\s+sips?:[^\s]+\s+SIP/2\.0\b")
_SIP_RESP = re.compile(r"\bSIP/2\.0\s+(\d{3})\s+([^\r\n]{0,80})")
_SIP_CALLID = re.compile(r"(?i)\bCall-ID:\s*(.+)")
_SIP_CODEC = re.compile(r"a=rtpmap:\d+\s+([A-Za-z0-9.\-]+)/\d+")

# Human-readable meaning for common SIP failure codes (call-setup diagnostics).
_SIP_CODE_MEANING = {
    401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    408: "Request Timeout", 480: "Temporarily Unavailable", 486: "Busy Here",
    487: "Request Terminated", 488: "Not Acceptable Here (codec/SDP mismatch)",
    500: "Server Internal Error", 502: "Bad Gateway",
    503: "Service Unavailable (gateway overload/down)", 504: "Server Time-out",
    600: "Busy Everywhere", 603: "Decline", 606: "Not Acceptable (media)",
}


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

        # Base structural analysis: text PCAP-AM wrapper, or binary packet parse.
        if self._is_text_file(filepath):
            result = self._analyze_pcap_am_text(filepath, filename, size_bytes)
        else:
            result = self._analyze_pcap_binary(filepath, filename, size_bytes)

        # SIP call analysis (dependency-free, streaming) — the primary voice diagnostic.
        # Runs for pcap, pcapng, and text wrappers; surfaces call-setup failures.
        sip = self._extract_sip(filepath, size_bytes)
        if sip:
            self._merge_sip(result, sip, filename)

        # If tshark IS installed, enrich with authoritative SIP call-flow extraction.
        tshark_path = self._find_tshark()
        if tshark_path and size_bytes < 500 * 1024 * 1024:
            tshark_result = self._analyze_with_tshark(tshark_path, filepath, filename)
            if tshark_result:
                result["findings"].extend(tshark_result.get("findings", []))
                result.setdefault("pcap_data", {}).update(tshark_result.get("tshark_data", {}))

        return result

    # ------------------------------------------------------------------
    # SIP extraction (no external dependencies)
    # ------------------------------------------------------------------

    def _extract_sip(self, filepath: str, size_bytes: int) -> Optional[Dict[str, Any]]:
        """Stream-scan raw capture bytes for SIP signalling, line by line.

        Bounded so very large captures stay cheap: we scan up to SCAN_CAP bytes of
        the file (SIP signalling packets are small and typically appear early/often).
        """
        SCAN_CAP = 150 * 1024 * 1024
        CHUNK = 4 * 1024 * 1024
        MAX_FAILURES = 100
        MAX_CALLS = 200000

        methods: Dict[str, int] = {}
        responses: Dict[int, int] = {}
        reasons: Dict[int, str] = {}
        failures: List[Dict[str, Any]] = []
        call_ids = set()
        codecs = set()
        msg_count = 0

        try:
            with open(filepath, "rb") as f:
                scanned = 0
                tail = ""
                while scanned < SCAN_CAP:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    scanned += len(chunk)
                    text = tail + chunk.decode("latin-1", errors="ignore")
                    lines = text.split("\n")
                    tail = lines.pop()  # carry the incomplete trailing line to next chunk
                    for line in lines:
                        if "SIP/2.0" not in line and "Call-ID" not in line and "rtpmap" not in line:
                            continue
                        mreq = _SIP_REQ.search(line)
                        if mreq:
                            methods[mreq.group(1)] = methods.get(mreq.group(1), 0) + 1
                            msg_count += 1
                        mresp = _SIP_RESP.search(line)
                        if mresp:
                            code = int(mresp.group(1))
                            responses[code] = responses.get(code, 0) + 1
                            reasons.setdefault(code, mresp.group(2).strip())
                            msg_count += 1
                            if code >= 400 and len(failures) < MAX_FAILURES:
                                failures.append({"code": code, "reason": mresp.group(2).strip()})
                        mcid = _SIP_CALLID.search(line)
                        if mcid and len(call_ids) < MAX_CALLS:
                            call_ids.add(mcid.group(1).strip()[:200])
                        mcodec = _SIP_CODEC.search(line)
                        if mcodec:
                            codecs.add(mcodec.group(1))
        except Exception:
            return None

        if msg_count == 0:
            return None

        fail_total = sum(cnt for code, cnt in responses.items() if code >= 400)
        return {
            "sip_message_count": msg_count,
            "call_count": len(call_ids),
            "methods": methods,
            "response_codes": {str(k): v for k, v in sorted(responses.items())},
            "reasons": {str(k): v for k, v in reasons.items()},
            "failure_count": fail_total,
            "codecs": sorted(codecs),
            "invite_count": methods.get("INVITE", 0),
            "scanned_bytes": scanned,
            "truncated_scan": size_bytes > SCAN_CAP,
        }

    def _merge_sip(self, result: Dict[str, Any], sip: Dict[str, Any], filename: str):
        """Fold SIP findings/evidence into the base result and pcap_data."""
        result.setdefault("findings", [])
        result.setdefault("evidence", [])
        result.setdefault("pcap_data", {})
        result["pcap_data"]["sip"] = sip

        calls = sip["call_count"]
        fails = sip["failure_count"]

        # Per-failure-code findings (5xx = ERROR, 4xx/6xx = WARN)
        responses = {int(k): v for k, v in sip["response_codes"].items()}
        for code in sorted(c for c in responses if c >= 400):
            cnt = responses[code]
            meaning = _SIP_CODE_MEANING.get(code, sip["reasons"].get(str(code), "Failure"))
            sev = "ERROR" if 500 <= code < 600 else "CRITICAL" if code >= 600 else "WARN"
            result["findings"].append({
                "severity": sev,
                "message": f"SIP {code} {meaning} in {filename} - {cnt} response(s): call-setup failure",
            })
            result["evidence"].append(f"SIP {code} {meaning} x{cnt}")

        if calls:
            result["evidence"].insert(0, f"SIP: {calls} call(s), {sip['invite_count']} INVITEs, {fails} failed setups"
                                          + (f", codecs {', '.join(sip['codecs'])}" if sip["codecs"] else ""))

        # Enrich the highlights line
        meta = result.get("metadata", {})
        sip_hl = f"SIP calls: {calls} | INVITEs: {sip['invite_count']} | failures: {fails}"
        if sip["codecs"]:
            sip_hl += f" | codecs: {', '.join(sip['codecs'])}"
        meta["highlights"] = (meta.get("highlights", "") + " || " + sip_hl).strip(" |")
        result["metadata"] = meta
        if result.get("metadata", {}).get("file_type", "").startswith("PCAP"):
            result["metadata"]["file_type"] = "PCAP / SIP Voice Capture"

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
        """Authoritative deep analysis via tshark CLI when Wireshark is installed."""
        import subprocess
        try:
            findings = []
            tshark_data = {}

            # Protocol hierarchy
            phs = subprocess.run(
                [tshark_path, "-r", filepath, "-q", "-z", "io,phs"],
                capture_output=True, text=True, timeout=60,
            )
            tshark_data["protocol_hierarchy"] = phs.stdout[:2000]

            # Per-message SIP fields: authoritative method / status extraction
            fields = subprocess.run(
                [tshark_path, "-r", filepath, "-Y", "sip", "-T", "fields",
                 "-e", "sip.Method", "-e", "sip.Status-Code", "-e", "sip.Status-Line",
                 "-E", "separator=|"],
                capture_output=True, text=True, timeout=90,
            )
            statuses: Dict[str, int] = {}
            for line in fields.stdout.splitlines():
                parts = line.split("|")
                code = parts[1].strip() if len(parts) > 1 else ""
                if code.isdigit() and int(code) >= 400:
                    statuses[code] = statuses.get(code, 0) + 1
            if statuses:
                tshark_data["sip_failure_codes"] = statuses
                for code, cnt in sorted(statuses.items()):
                    ic = int(code)
                    sev = "ERROR" if 500 <= ic < 600 else "CRITICAL" if ic >= 600 else "WARN"
                    findings.append({
                        "severity": sev,
                        "message": f"[tshark] SIP {code} {_SIP_CODE_MEANING.get(ic, '')} x{cnt} in {filename}",
                    })

            # RTP stream quality (jitter / packet loss) if present
            rtp = subprocess.run(
                [tshark_path, "-r", filepath, "-q", "-z", "rtp,streams"],
                capture_output=True, text=True, timeout=60,
            )
            if rtp.stdout and "SSRC" in rtp.stdout:
                tshark_data["rtp_streams"] = rtp.stdout[:2000]

            return {"findings": findings, "tshark_data": tshark_data}
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
        calls = 0
        fails = 0
        for ctx in result.pcap_context.values():
            sip = ctx.get("sip") if isinstance(ctx, dict) else None
            if sip:
                calls += sip.get("call_count", 0)
                fails += sip.get("failure_count", 0)
        base = f"Analyzed {result.file_count} PCAP/SIP files. {total_packets:,} packets captured."
        if calls or fails:
            base += f" {calls} SIP call(s), {fails} call-setup failure(s) detected."
        return base
