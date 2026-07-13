"""
backend/core/ingestion.py

Adaptive, multi-source ingestion (requirements: seamless 8-10GB, dynamic sizing,
local/share + cloud sources).

Two responsibilities:
  1. IngestionPlanner — pre-scan any source and derive an *adaptive budget* (worker
     count + memory caps) scaled to the measured data size, so processing bounds
     memory automatically instead of assuming a fixed input size.
  2. Source resolvers — turn a local/share path or a cloud (S3) URI into a local
     directory the pipeline can analyze, streaming large downloads to disk.

Nothing here assumes a size: an 8-10GB bundle gets bounded caps and more workers; a
handful of KB gets the full-fidelity treatment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


# Size tiers (bytes). Caps are chosen so retained structured logs stay well within
# memory even for very large bundles, while preserving full diagnostic signal.
_MB = 1024 * 1024
_GB = 1024 * _MB


@dataclass
class IngestionProfile:
    total_bytes: int
    file_count: int
    largest_file_bytes: int
    tier: str                    # small | medium | large | xlarge
    max_workers: int
    max_structured_entries: Optional[int]
    max_raw_chars: int
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["total_human"] = _human(self.total_bytes)
        d["largest_human"] = _human(self.largest_file_bytes)
        return d


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < _MB:
        return f"{n / 1024:.1f} KB"
    if n < _GB:
        return f"{n / _MB:.1f} MB"
    return f"{n / _GB:.2f} GB"


class IngestionPlanner:
    """Scans a directory and derives an adaptive processing budget."""

    @staticmethod
    def scan(dir_path: str) -> IngestionProfile:
        total = 0
        count = 0
        largest = 0
        for root, _dirs, files in os.walk(dir_path):
            for f in files:
                try:
                    sz = os.path.getsize(os.path.join(root, f))
                except OSError:
                    continue
                total += sz
                count += 1
                largest = max(largest, sz)
        return IngestionPlanner.plan(total, count, largest)

    @staticmethod
    def plan(total_bytes: int, file_count: int, largest_file_bytes: int = 0) -> IngestionProfile:
        cpu = os.cpu_count() or 4

        if total_bytes < 256 * _MB:
            tier, cap, raw = "small", None, 4 * _MB
            note = "Full-fidelity parse."
        elif total_bytes < 2 * _GB:
            tier, cap, raw = "medium", 150_000, 3 * _MB
            note = "Bounded parse; all errors retained, verbose logs sampled."
        elif total_bytes < 8 * _GB:
            tier, cap, raw = "large", 80_000, 2 * _MB
            note = "Large bundle: aggressive bounding, more parallel workers."
        else:
            tier, cap, raw = "xlarge", 50_000, 2 * _MB
            note = "Very large bundle: max bounding to guarantee stable memory."

        # More files -> more parallel type-agents help; single huge files don't.
        if tier in ("large", "xlarge"):
            max_workers = min(max(cpu, 6), 12)
        elif file_count > 8:
            max_workers = min(cpu, 8)
        else:
            max_workers = min(cpu, 4)

        return IngestionProfile(
            total_bytes=total_bytes, file_count=file_count,
            largest_file_bytes=largest_file_bytes, tier=tier,
            max_workers=max_workers, max_structured_entries=cap,
            max_raw_chars=raw, note=note,
        )


# ---------------------------------------------------------------------------
# Source resolvers
# ---------------------------------------------------------------------------

class IngestionError(Exception):
    pass


def resolve_local_path(path: str) -> str:
    """Validate a local/share path the backend can read. Returns a directory path.

    In production, restrict readable roots via LOGSENTRY_ALLOWED_ROOTS (os.pathsep-
    separated). If unset (dev), any existing absolute path is allowed.
    """
    if not path:
        raise IngestionError("No path provided.")
    ap = os.path.abspath(path)
    if not os.path.exists(ap):
        raise IngestionError(f"Path does not exist: {ap}")

    allowed = os.getenv("LOGSENTRY_ALLOWED_ROOTS", "").strip()
    if allowed:
        roots = [os.path.abspath(r) for r in allowed.split(os.pathsep) if r.strip()]
        if not any(ap == r or ap.startswith(r + os.sep) for r in roots):
            raise IngestionError("Path is outside the allowed roots.")

    return ap


def download_s3(uri: str, dest_dir: str, chunk_mb: int = 16) -> int:
    """Download all objects under an s3://bucket/prefix URI into dest_dir (streamed).

    Requires boto3 (already a dependency for Bedrock) and standard AWS credentials.
    Returns the number of objects downloaded.
    """
    if not uri.startswith("s3://"):
        raise IngestionError("Cloud URI must start with s3://")
    try:
        import boto3  # noqa
    except ImportError:
        raise IngestionError("boto3 is not installed; cannot fetch from S3.")

    without = uri[len("s3://"):]
    bucket, _, prefix = without.partition("/")
    if not bucket:
        raise IngestionError("Malformed S3 URI; expected s3://bucket/prefix")

    s3 = boto3.client("s3")
    os.makedirs(dest_dir, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            # Flatten the key into a safe local filename, preserving basename uniqueness
            safe = key.replace("/", "__")
            target = os.path.join(dest_dir, safe)
            s3.download_file(bucket, key, target)
            n += 1
    if n == 0:
        raise IngestionError(f"No objects found at {uri}")
    return n
