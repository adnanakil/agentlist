import json
import os
import sys
import traceback

import httpx


def handle(input_data: dict) -> dict:
    """Call Claude API and return the response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    prompt = input_data.get("prompt", "")
    system = input_data.get("system", "You are a helpful assistant.")
    max_tokens = input_data.get("max_tokens", 1024)

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )

    if response.status_code != 200:
        return {
            "error": f"Claude API error: {response.status_code}",
            "details": response.text[:500],
        }

    data = response.json()
    text = data["content"][0]["text"] if data.get("content") else ""

    return {
        "response": text,
        "model": data.get("model", ""),
        "usage": data.get("usage", {}),
    }


if __name__ == "__main__":
    try:
        raw_input = os.environ.get("AGENT_INPUT", "{}")
        input_data = json.loads(raw_input)
        result = handle(input_data)
        output = {"success": True, "data": result}
    except Exception as e:
        output = {"success": False, "error": str(e), "traceback": traceback.format_exc()}

    json.dump(output, sys.stdout)
    sys.stdout.flush()
