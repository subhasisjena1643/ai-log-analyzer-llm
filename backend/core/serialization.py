"""
backend/core/serialization.py

Converts the pipeline's internal objects (LogEntry dataclasses, agent context
dicts, numpy scalars, datetimes) into plain JSON-serializable structures for the
FastAPI layer. Keeps the API boundary decoupled from backend object shapes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _scalar(value: Any) -> Any:
    # numpy scalar -> python scalar (without importing numpy hard-dependency)
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def to_jsonable(obj: Any) -> Any:
    """Recursively convert an object graph into JSON-safe primitives."""
    # LogEntry and similar objects expose to_dict()
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        return to_jsonable(obj.to_dict())

    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]

    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj

    # dataclass-like fallback
    if hasattr(obj, "__dict__"):
        return {str(k): to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}

    return _scalar(obj)


def serialize_log_entry(entry: Any) -> dict:
    """Serialize a single LogEntry into the API shape (client/zone omitted for NDA)."""
    d = entry.to_dict() if hasattr(entry, "to_dict") else dict(getattr(entry, "__dict__", {}))
    # Drop client-identifying fields at the serialization boundary (requirement #4).
    for confidential in ("client", "zone"):
        d.pop(confidential, None)
    return to_jsonable(d)
