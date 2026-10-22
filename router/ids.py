"""Task IDs: sr-YYYYMMDD-HHMMSS-xxxx (UTC time + 4 random hex chars)."""
import secrets
from datetime import datetime, timezone


def new_task_id(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"sr-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
