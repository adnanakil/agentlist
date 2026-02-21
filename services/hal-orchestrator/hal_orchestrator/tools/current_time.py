"""current_time tool — returns the current date and time."""

from __future__ import annotations

from datetime import datetime, timezone


def tool_current_time() -> str:
    """Return the current date and time in a human-readable format."""
    now = datetime.now(timezone.utc)
    # Format: "Monday, February 10, 2026 at 2:30 PM UTC"
    return now.strftime("%A, %B %d, %Y at %-I:%M %p UTC")
