# src/services/anomaly_detector.py

from collections import defaultdict
from datetime import datetime
from typing import List


def _parse_log_timestamp(timestamp):
    if not timestamp:
        return None
    if isinstance(timestamp, datetime):
        return timestamp
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(str(timestamp), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_error_anomaly(structured_logs: List, threshold: int = 5, bucket_minutes: int = 5) -> dict:
    """
    Anomaly detection based on error count and time-bucketed spike detection.
    Returns all keys expected by app.py.
    """
    error_logs = [
        log for log in structured_logs
        if getattr(log, "log_level", "").upper() == "ERROR"
        or "error" in str(log).lower()
    ]
    error_count = len(error_logs)
    buckets = defaultdict(int)

    for log in error_logs:
        parsed_time = _parse_log_timestamp(getattr(log, "timestamp", None))
        if not parsed_time:
            continue
        bucket_minute = (parsed_time.minute // bucket_minutes) * bucket_minutes
        bucket_time = parsed_time.replace(minute=bucket_minute, second=0, microsecond=0)
        buckets[bucket_time] += 1

    spike_time = None
    spike_count = 0
    if buckets:
        spike_time, spike_count = max(buckets.items(), key=lambda item: item[1])

    spike_detected = spike_count >= threshold
    count_anomaly = error_count > threshold
    anomaly_flag = spike_detected or count_anomaly

    if spike_detected:
        explanation = (
            f"Error spike detected at {spike_time.strftime('%I:%M %p')}.\n\n"
            f"Reason:\n{spike_count} errors occurred within a "
            f"{bucket_minutes}-minute window, meeting the spike threshold of {threshold}.\n\n"
            "This indicates concentrated failure activity rather than isolated errors."
        )
    elif count_anomaly:
        explanation = (
            "An anomaly has been detected in the system logs.\n\n"
            f"Reason:\nThe observed error count ({error_count}) exceeded the "
            f"predefined threshold ({threshold}).\n\n"
            "This indicates abnormal system behavior such as repeated failures "
            "or operational instability."
        )
    else:
        explanation = (
            "No anomaly detected.\n\n"
            f"The total error count ({error_count}) is within the acceptable "
            f"threshold ({threshold}), and no time-based error spike was found."
        )

    return {
        "anomaly_detected": anomaly_flag,
        "message": explanation,
        "error_count": error_count,
        "threshold": threshold,
        "bucket_minutes": bucket_minutes,
        "spike_detected": spike_detected,
        "spike_time": spike_time.strftime("%I:%M %p") if spike_time else None,
        "spike_count": spike_count,
        "error_frequency": [
            {"time": bucket_time.strftime("%I:%M %p"), "count": count}
            for bucket_time, count in sorted(buckets.items())
        ],
    }
