"""Time-now agent — returns the current time in any timezone."""

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def handle(input_data: dict) -> dict:
    tz_name = input_data.get("timezone", "UTC")

    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        return {"error": f"Unknown timezone: {tz_name}"}

    now = datetime.now(timezone.utc).astimezone(tz)

    return {
        "time": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "date": now.strftime("%A, %B %d, %Y"),
        "timezone": tz_name,
        "utc_offset": now.strftime("%z"),
    }


if __name__ == "__main__":
    raw_input = os.environ.get("AGENT_INPUT", "{}")
    input_data = json.loads(raw_input)
    result = handle(input_data)
    json.dump(result, sys.stdout)
    sys.stdout.flush()
