"""Date parsing via Gemini Flash — extracts availability from natural language."""

from __future__ import annotations

import json
from datetime import date

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig
from hal_orchestrator.services.gemini import call_gemini

log = structlog.get_logger()

PARSE_PROMPT = """\
Extract travel dates from this message. Return ONLY valid JSON, nothing else.

Format:
{{"available": [{{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}], "unavailable": ["YYYY-MM-DD"], "none": false}}

Rules:
- If the message contains available date ranges, list them in "available"
- If the message says they can't do specific dates, list those in "unavailable"
- If no dates are found at all, return {{"none": true}}
- "Any weekend in April" = list each weekend Fri-Sun in April as separate ranges
- "March 20-25" = {{"start": "YYYY-03-20", "end": "YYYY-03-25"}}
- "Not the 15th" = add to unavailable
- Use the current year unless another year is specified

Today's date: {today}
Trip location: {location}

Message: "{text}"
"""


async def parse_dates(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    text: str,
    location: str,
) -> dict:
    """Parse natural language dates using Gemini Flash.

    Returns: {"available": [...], "unavailable": [...], "none": bool}
    """
    today = date.today().isoformat()
    prompt = PARSE_PROMPT.format(today=today, location=location, text=text)

    history = [{"role": "user", "parts": [{"text": prompt}]}]

    response = await call_gemini(
        client=client,
        settings=settings,
        history=history,
        tools=None,
        system="You are a date extraction tool. Return only valid JSON.",
        model="flash",
    )

    if not response:
        log.warning("date_parser.no_response")
        return {"none": True}

    candidates = response.get("candidates", [])
    if not candidates:
        return {"none": True}

    parts = candidates[0].get("content", {}).get("parts", [])
    raw = "".join(p.get("text", "") for p in parts).strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        log.info("date_parser.success", result=parsed)
        return parsed
    except json.JSONDecodeError:
        log.warning("date_parser.invalid_json", raw=raw[:200])
        return {"none": True}
