# src/services/automated_rca.py

def generate_automated_rca(anomaly_result: dict, time_corr_result: dict, total_errors: int) -> str:
    """Generates a final automated RCA summary"""
    rca_lines = []

    rca_lines.append(f"Total ERROR events detected: {total_errors}.")

    # FIX: correct key is "anomaly_detected", not "anomaly"
    if anomaly_result.get("anomaly_detected"):
        rca_lines.append(
            f"Anomaly detected: {anomaly_result.get('message', 'Error spike identified')}."
        )
    else:
        rca_lines.append("No abnormal error spike detected.")

    if time_corr_result.get("correlated"):
        rca_lines.append(
            "Multiple errors occurred in close time intervals, indicating a cascading failure."
        )
    else:
        rca_lines.append(
            "Errors are spread over time with no strong temporal correlation."
        )

    rca_lines.append(
        "Root cause is likely due to service instability or configuration issues "
        "rather than a single isolated failure."
    )

    return " ".join(rca_lines)
