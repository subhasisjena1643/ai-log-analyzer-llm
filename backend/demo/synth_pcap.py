"""
backend/demo/synth_pcap.py

Generates a synthetic, NDA-neutral classic-pcap capture containing SIP call
signalling (INVITE / responses / SDP), so the PCAP/SIP analyzer can be built and
verified without any real capture (all captures are under NDA). Neutral IPs only.

Usage:
    python -m backend.demo.synth_pcap out.pcap            # a failing-call capture
    python -m backend.demo.synth_pcap out.pcap --ok       # a successful call
"""

from __future__ import annotations

import struct
import sys


def _ip(addr: str) -> bytes:
    return bytes(int(x) for x in addr.split("."))


def _udp_ip_eth(payload: bytes, src="10.20.0.11", dst="10.20.0.12", sport=5060, dport=5060) -> bytes:
    udp_len = 8 + len(payload)
    udp = struct.pack(">HHHH", sport, dport, udp_len, 0) + payload
    total_len = 20 + udp_len
    ip = struct.pack(">BBHHHBBH", 0x45, 0, total_len, 0, 0, 64, 17, 0) + _ip(src) + _ip(dst)
    eth = b"\xaa\xbb\xcc\xdd\xee\x01\xaa\xbb\xcc\xdd\xee\x02\x08\x00"
    return eth + ip + udp


def _record(ts_sec: int, ts_usec: int, data: bytes) -> bytes:
    return struct.pack("<IIII", ts_sec, ts_usec, len(data), len(data)) + data


def _sip(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def build(path: str, ok: bool = False) -> None:
    call_id = "a84b4c76e66710@10.20.0.11"
    invite = _sip([
        "INVITE sip:trader@voice.internal SIP/2.0",
        "Via: SIP/2.0/UDP 10.20.0.11:5060",
        "From: <sip:console-07@voice.internal>;tag=1928",
        "To: <sip:trader@voice.internal>",
        f"Call-ID: {call_id}",
        "CSeq: 1 INVITE",
        "Content-Type: application/sdp",
        "",
        "v=0", "m=audio 40000 RTP/AVP 0 8 18",
        "a=rtpmap:0 PCMU/8000", "a=rtpmap:8 PCMA/8000", "a=rtpmap:18 G729/8000",
    ])
    trying = _sip(["SIP/2.0 100 Trying", f"Call-ID: {call_id}", "CSeq: 1 INVITE"])

    if ok:
        r1 = _sip(["SIP/2.0 180 Ringing", f"Call-ID: {call_id}", "CSeq: 1 INVITE"])
        r2 = _sip(["SIP/2.0 200 OK", f"Call-ID: {call_id}", "CSeq: 1 INVITE"])
        packets = [invite, trying, r1, r2]
    else:
        # Media gateway overloaded -> 503, then the call is torn down
        r1 = _sip(["SIP/2.0 100 Trying", f"Call-ID: {call_id}", "CSeq: 1 INVITE"])
        r2 = _sip(["SIP/2.0 503 Service Unavailable", f"Call-ID: {call_id}",
                   "CSeq: 1 INVITE", "Reason: Q.850;cause=41;text=\"gateway overload\""])
        # a second call that fails with 488 codec mismatch
        cid2 = "bb99ff22aa@10.20.0.13"
        inv2 = _sip(["INVITE sip:trader2@voice.internal SIP/2.0", f"Call-ID: {cid2}",
                     "Content-Type: application/sdp", "", "m=audio 40002 RTP/AVP 18", "a=rtpmap:18 G729/8000"])
        r3 = _sip(["SIP/2.0 488 Not Acceptable Here", f"Call-ID: {cid2}", "CSeq: 1 INVITE"])
        packets = [invite, trying, r1, r2, inv2, r3]

    with open(path, "wb") as f:
        # pcap global header: magic, ver 2.4, thiszone, sigfigs, snaplen, linktype=1 (Ethernet)
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        ts = 1_700_000_000
        for i, p in enumerate(packets):
            f.write(_record(ts, i * 1000, _udp_ip_eth(p)))
    print(f"Wrote {path} ({len(packets)} SIP packets, {'successful' if ok else 'failing'} call scenario)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "synth.pcap"
    build(out, ok="--ok" in sys.argv)
