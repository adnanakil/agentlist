"""Tests for the GLM (Z.ai) provider shim — request-body shape + dispatch
routing (no network).

Run: python3 services/hal-orchestrator/tests_glm_provider.py
"""

import asyncio
import json
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import gemini as GM
from hal_orchestrator.services import glm_provider as G

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


HIST = [{"role": "user", "parts": [{"text": "hi"}]}]
TOOLS = [{"function_declarations": [
    {"name": "baby", "description": "track", "parameters": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
]}]

print("request body is lean (no Anthropic-only knobs):")
body = G._build_glm_body(HIST, TOOLS, "SYSTEM PROMPT", "glm-5.2", 8000)
check("model set", body["model"] == "glm-5.2")
check("max_tokens passed", body["max_tokens"] == 8000)
check("no thinking", "thinking" not in body)
check("no output_config", "output_config" not in body)
check("system is a plain string (not a cache_control block list)", body["system"] == "SYSTEM PROMPT")
check("no cache_control anywhere", "cache_control" not in json.dumps(body))
check("messages translated", body["messages"][0]["role"] == "user")
check("tools translated to input_schema", body["tools"][0]["name"] == "baby" and "input_schema" in body["tools"][0])

print("body defaults + omissions:")
bare = G._build_glm_body(HIST, None, None, "glm-5.2", None)
check("default max_tokens 16000", bare["max_tokens"] == 16000)
check("no tools key when none", "tools" not in bare)
check("no system key when none", "system" not in bare)

print("response translation is reused from the Claude shim:")
g = G._to_gemini_response({"stop_reason": "tool_use", "content": [
    {"type": "text", "text": "ok"},
    {"type": "tool_use", "id": "call_1", "name": "baby", "input": {"action": "log"}},
]})
parts = g["candidates"][0]["content"]["parts"]
check("finishReason tool_use -> TOOL_CALLS", g["candidates"][0]["finishReason"] == "TOOL_CALLS")
check("tool_use -> functionCall + stashed id", any(p.get("functionCall", {}).get("name") == "baby" and p.get("_claude_block", {}).get("id") == "call_1" for p in parts))

print("dispatch routes glm-* to call_glm (and other ids do NOT):")


async def _route(model):
    seen = {}

    async def fake_call_glm(client, settings, history, tools, system, m, *a, **k):
        seen["glm"] = m
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    async def fake_native(client, settings, history, tools, system, m, *a, **k):
        seen["native"] = m
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    orig_glm, orig_native = G.call_glm, GM._call_gemini_native
    G.call_glm = fake_call_glm
    GM._call_gemini_native = fake_native
    try:
        await GM._dispatch_model(None, None, HIST, None, None, model, 1, None, None, is_primary=True)
    finally:
        G.call_glm, GM._call_gemini_native = orig_glm, orig_native
    return seen


s1 = asyncio.run(_route("glm-5.2"))
check("glm-5.2 -> call_glm", s1.get("glm") == "glm-5.2" and "native" not in s1)
s2 = asyncio.run(_route("gemini-3.5-flash"))
check("gemini-* -> native (not GLM)", s2.get("native") == "gemini-3.5-flash" and "glm" not in s2)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
