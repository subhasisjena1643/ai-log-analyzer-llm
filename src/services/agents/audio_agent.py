# src/services/agents/audio_agent.py
"""
AudioAgent: Analyzer for audio-related files.
Handles:
  - Text-based Call Detail Records (CDRs)
  - .wav/.mp3/.ogg/.flac metadata extraction (duration, codec, sample rate)
  - Speech-to-text stub for future transcription integration
"""

import os
import re
import struct
from typing import Dict, List, Any, Optional

from src.services.agent_framework import BaseAgent


class AudioAgent(BaseAgent):
    AGENT_NAME = "audio"

    def analyze(self, filepath: str, filename: str, **kwargs) -> Dict[str, Any]:
        size_bytes = self.safe_file_size(filepath)
        filename_lower = filename.lower()

        # Route by extension
        if filename_lower.endswith(".wav"):
            return self._analyze_wav(filepath, filename, size_bytes)
        elif filename_lower.endswith((".mp3", ".ogg", ".flac")):
            return self._analyze_with_mutagen(filepath, filename, size_bytes)
        else:
            # Assume text-based CDR or audio log
            return self._analyze_cdr_text(filepath, filename, size_bytes)

    # -----------------------------------------------------------------------
    # WAV File Analysis (native — no external deps)
    # -----------------------------------------------------------------------
    def _analyze_wav(self, filepath, filename, size_bytes):
        """Parse WAV header natively using struct."""
        findings = []
        metadata = {}

        try:
            import wave
            with wave.open(filepath, "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                frames = wf.getnframes()
                sample_width = wf.getsampwidth()
                duration_sec = frames / sample_rate if sample_rate > 0 else 0

                metadata = {
                    "channels": channels,
                    "sample_rate": sample_rate,
                    "frames": frames,
                    "sample_width_bytes": sample_width,
                    "duration_seconds": round(duration_sec, 2),
                    "duration_formatted": self._format_duration(duration_sec),
                    "codec": f"PCM {sample_width * 8}-bit",
                }

                if duration_sec > 3600:
                    findings.append({
                        "severity": "INFO",
                        "message": f"Long audio recording: {self._format_duration(duration_sec)} in {filename}",
                    })

        except Exception as e:
            # Fallback: read raw WAV header bytes
            metadata = self._read_wav_header_raw(filepath)
            if not metadata:
                return {
                    "findings": [{"severity": "WARN", "message": f"Could not parse WAV {filename}: {e}"}],
                    "metadata": {"filename": filename, "file_type": "Audio (WAV)", "size": self.format_size(size_bytes), "highlights": "Parse error"},
                    "audio_data": {"filename": filename, "error": str(e)},
                }

        duration_str = metadata.get("duration_formatted", "N/A")
        codec = metadata.get("codec", "Unknown")
        highlights = f"WAV | Duration: {duration_str} | Codec: {codec} | Rate: {metadata.get('sample_rate', 'N/A')} Hz"

        audio_data = {"filename": filename, "type": "wav", **metadata}

        return {
            "findings": findings,
            "evidence": [f"Audio: {filename} — {duration_str}, {codec}"],
            "metrics": metadata,
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "Audio (WAV)", "size": self.format_size(size_bytes), "highlights": highlights},
            "audio_data": audio_data,
        }

    # -----------------------------------------------------------------------
    # MP3/OGG/FLAC Analysis (via mutagen if available)
    # -----------------------------------------------------------------------
    def _analyze_with_mutagen(self, filepath, filename, size_bytes):
        """Parse audio metadata using mutagen library."""
        findings = []
        metadata = {}

        try:
            import mutagen
            audio = mutagen.File(filepath)
            if audio is None:
                raise ValueError("Mutagen could not identify format")

            duration_sec = audio.info.length if hasattr(audio.info, "length") else 0
            sample_rate = getattr(audio.info, "sample_rate", None)
            channels = getattr(audio.info, "channels", None)
            bitrate = getattr(audio.info, "bitrate", None)

            metadata = {
                "duration_seconds": round(duration_sec, 2),
                "duration_formatted": self._format_duration(duration_sec),
                "sample_rate": sample_rate,
                "channels": channels,
                "bitrate": bitrate,
                "codec": type(audio).__name__,
            }

        except ImportError:
            # mutagen not installed — extract basic info
            ext = os.path.splitext(filename)[1].upper().strip(".")
            metadata = {"note": f"Install mutagen for {ext} metadata extraction"}
            findings.append({
                "severity": "INFO",
                "message": f"{ext} file detected ({self.format_size(size_bytes)}). Install mutagen for metadata extraction.",
            })
        except Exception as e:
            metadata = {"error": str(e)}
            findings.append({
                "severity": "WARN",
                "message": f"Could not parse audio file {filename}: {e}",
            })

        duration_str = metadata.get("duration_formatted", "N/A")
        ext = os.path.splitext(filename)[1].upper().strip(".")
        highlights = f"{ext} | Duration: {duration_str} | Size: {self.format_size(size_bytes)}"

        audio_data = {"filename": filename, "type": ext.lower(), **metadata}

        return {
            "findings": findings,
            "evidence": [f"Audio: {filename} — {duration_str}"] if duration_str != "N/A" else [],
            "metrics": metadata,
            "metadata": {"filename": filename, "relative_path": filename, "file_type": f"Audio ({ext})", "size": self.format_size(size_bytes), "highlights": highlights},
            "audio_data": audio_data,
        }

    # -----------------------------------------------------------------------
    # Text-based CDR / Audio Log Analysis
    # -----------------------------------------------------------------------
    def _analyze_cdr_text(self, filepath, filename, size_bytes):
        """Parse text-based Call Detail Records or audio event logs."""
        findings = []
        total_calls = 0
        failed_calls = 0
        codecs_seen = set()
        endpoints = set()
        total_duration_sec = 0
        preview_lines = []
        total_lines = 0

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_lines += 1
                    if total_lines <= 100:
                        preview_lines.append(line)

                    stripped = line.strip()
                    line_lower = stripped.lower()

                    # Detect call records
                    if any(k in line_lower for k in ["call_id", "callid", "session_id", "call detail"]):
                        total_calls += 1

                    # Detect failures
                    if any(k in line_lower for k in ["fail", "error", "rejected", "timeout", "busy", "unavailable", "503", "486"]):
                        failed_calls += 1

                    # Detect codecs
                    codec_match = re.search(r"(?:codec|payload)[:\s=]*([A-Za-z0-9.]+(?:\s*/\s*\d+)?)", line, re.IGNORECASE)
                    if codec_match:
                        codecs_seen.add(codec_match.group(1).strip())

                    # Detect G.7xx codecs inline
                    g_codec = re.search(r"(G\.\d{3}(?:a|b)?)", line, re.IGNORECASE)
                    if g_codec:
                        codecs_seen.add(g_codec.group(1).upper())

                    # Detect duration values
                    dur_match = re.search(r"(?:duration|length)[:\s=]*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", line, re.IGNORECASE)
                    if dur_match:
                        total_duration_sec += float(dur_match.group(1))

                    # Detect endpoints / phone numbers / extensions
                    ext_match = re.search(r"(?:extension|endpoint|number|uri)[:\s=]*([^\s,;]+)", line, re.IGNORECASE)
                    if ext_match and len(endpoints) < 50:
                        endpoints.add(ext_match.group(1).strip())

        except Exception as e:
            return {
                "findings": [{"severity": "ERROR", "message": f"Failed to parse CDR {filename}: {e}"}],
                "metadata": {"filename": filename, "file_type": "Audio CDR/Log", "size": self.format_size(size_bytes), "highlights": "Parse error"},
                "audio_data": {"filename": filename, "error": str(e)},
            }

        if failed_calls > 0:
            fail_rate = (failed_calls / total_calls * 100) if total_calls > 0 else 0
            severity = "ERROR" if fail_rate > 10 else "WARN"
            findings.append({
                "severity": severity,
                "message": f"{failed_calls} failed calls detected ({fail_rate:.1f}% failure rate) in {filename}",
            })

        codecs_str = ", ".join(sorted(codecs_seen)) if codecs_seen else "N/A"
        highlights = f"CDR: {total_calls} calls | Failed: {failed_calls} | Codecs: {codecs_str}"

        audio_data = {
            "filename": filename,
            "type": "cdr_text",
            "total_calls": total_calls,
            "failed_calls": failed_calls,
            "codecs": sorted(codecs_seen),
            "endpoints_count": len(endpoints),
            "total_duration_seconds": round(total_duration_sec, 2),
            "total_duration_formatted": self._format_duration(total_duration_sec),
            "preview": "".join(preview_lines),
        }

        return {
            "findings": findings,
            "evidence": [f"CDR: {total_calls} calls, {failed_calls} failures"] if total_calls > 0 else [],
            "metrics": {"total_calls": total_calls, "failed_calls": failed_calls, "codecs": sorted(codecs_seen)},
            "metadata": {"filename": filename, "relative_path": filename, "file_type": "Audio CDR/Log", "size": self.format_size(size_bytes), "highlights": highlights},
            "audio_data": audio_data,
        }

    # -----------------------------------------------------------------------
    # Speech-to-Text Stub
    # -----------------------------------------------------------------------
    @staticmethod
    def transcribe_audio(filepath: str) -> Optional[str]:
        """
        Stub for speech-to-text transcription.
        Future integration: AWS Transcribe, Whisper, or Google Speech-to-Text.
        """
        # Phase 2: Integrate with AWS Transcribe via Bedrock or standalone
        # import boto3
        # client = boto3.client('transcribe')
        # ...
        return None

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _read_wav_header_raw(self, filepath) -> Optional[Dict]:
        """Fallback raw WAV header reader using struct."""
        try:
            with open(filepath, "rb") as f:
                riff = f.read(4)
                if riff != b"RIFF":
                    return None
                f.read(4)  # file size
                wave_id = f.read(4)
                if wave_id != b"WAVE":
                    return None
                # Find fmt chunk
                while True:
                    chunk_id = f.read(4)
                    if len(chunk_id) < 4:
                        break
                    chunk_size = struct.unpack("<I", f.read(4))[0]
                    if chunk_id == b"fmt ":
                        fmt_data = f.read(min(chunk_size, 16))
                        audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack("<HHIIHH", fmt_data[:16])
                        # Estimate duration from file size
                        file_size = os.path.getsize(filepath)
                        duration_sec = (file_size - 44) / byte_rate if byte_rate > 0 else 0
                        return {
                            "channels": channels,
                            "sample_rate": sample_rate,
                            "sample_width_bytes": bits_per_sample // 8,
                            "duration_seconds": round(duration_sec, 2),
                            "duration_formatted": self._format_duration(duration_sec),
                            "codec": f"PCM {bits_per_sample}-bit" if audio_format == 1 else f"Format-{audio_format}",
                        }
                    else:
                        f.seek(chunk_size, 1)
        except Exception:
            return None

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into HH:MM:SS."""
        if seconds <= 0:
            return "0:00"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _merge_file_result(self, batch_result, file_result, filename):
        super()._merge_file_result(batch_result, file_result, filename)
        if "audio_data" in file_result:
            batch_result.audio_context[filename] = file_result["audio_data"]

    def _generate_summary(self, result):
        total_calls = sum(m.get("total_calls", 0) for m in result.metrics.values() if isinstance(m, dict))
        failed = sum(m.get("failed_calls", 0) for m in result.metrics.values() if isinstance(m, dict))
        parts = [f"Analyzed {result.file_count} audio/CDR files."]
        if total_calls > 0:
            parts.append(f"{total_calls} call records, {failed} failures.")
        return " ".join(parts)
