import math

PREPARE_SECONDS = 3.0
ACTION_SECONDS = 5.0
REST_SECONDS = 0.0


def preparation_countdown(status):
    """Match the host: show zero in the last 0.3 s, without extending preparation."""
    if status.get("done") or status.get("phase") != "准备":
        return None
    remaining = status["remaining"]
    return 0 if remaining <= 0.3 else math.ceil(remaining)
