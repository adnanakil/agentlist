"""Tests for the OpenAI provider shim's pure translation logic (no API).

Run: python3 services/hal-orchestrator/tests_openai_provider.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import openai_provider as O

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("tools translation (flat Responses-API format):")
tools = [{"function_declarations": [
    {"name": "baby", "description": "track", "parameters": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
    {"name": "get_weather", "description": "wx", "parameters": {"type": "object", "properties": {}}},
]}]
ot = O._to_openai_tools(tools)
check("count", len(ot) == 2)
check("flat shape (no nested function key)", all(t["type"] == "function" and "name" in t and "parameters" in t and "function" not in t for t in ot))
check("schema carried", ot[0]["parameters"]["required"] == ["action"])
check("missing parameters -> empty object schema",
      O._to_openai_tools([{"function_declarations": [{"name": "x"}]}])[0]["parameters"] == {"type": "object", "properties": {}})

print("multi-turn round-trip (positional id pairing):")
history = [
    {"role": "user", "parts": [{"text": "is it raining?"}]},
    {"role": "model", "parts": [
        {"text": "Checking."},
        {"functionCall": {"name": "get_weather", "args": {"location": "NYC"}}},
        {"functionCall": {"name": "current_time", "args": {}}},
    ]},
    {"role": "user", "parts": [
        {"functionResponse": {"name": "get_weather", "response": {"content": "dry"}}},
        {"functionResponse": {"name": "current_time", "response": {"content": "3pm"}}},
    ]},
]
items = O._to_openai_input(history)
types = [(it.get("role") or it.get("type")) for it in items]
check("item stream", types == ["user", "assistant", "function_call", "function_call_output", "function_call", "function_call_output"])
check("assistant text kept alongside calls", items[1]["content"] == [{"type": "output_text", "text": "Checking."}])
calls = [it for it in items if it.get("type") == "function_call"]
outs = [it for it in items if it.get("type") == "function_call_output"]
check("arguments JSON-encoded", calls[0]["arguments"] == '{"location": "NYC"}')
check("ids pair positionally", [c["call_id"] for c in calls] == [o["call_id"] for o in outs])
check("distinct ids", calls[0]["call_id"] != calls[1]["call_id"])
check("output content carried", outs[0]["output"] == "dry" and outs[1]["output"] == "3pm")

print("claude-primary residue ignored:")
residue = [
    {"role": "user", "parts": [{"text": "hi"}]},
    {"role": "model", "parts": [
        {"_claude_block": {"type": "thinking", "thinking": "hmm", "signature": "SIG"}},
        {"text": "hello"},
    ]},
]
items = O._to_openai_input(residue)
check("thinking-only part dropped", [(it.get("role") or it.get("type")) for it in items] == ["user", "assistant"])
check("text survives", items[1]["content"][0]["text"] == "hello")

print("orphaned functionResponse skipped (trimmed history):")
orphan = [
    {"role": "user", "parts": [{"functionResponse": {"name": "x", "response": {"content": "r"}}}]},
    {"role": "user", "parts": [{"text": "hi"}]},
]
items = O._to_openai_input(orphan)
check("no output item without a call", [(it.get("role") or it.get("type")) for it in items] == ["user"])

print("dangling function_call dropped (trimmed history):")
dangling = [
    {"role": "user", "parts": [{"text": "hi"}]},
    {"role": "model", "parts": [{"text": "on it"}, {"functionCall": {"name": "x", "args": {}}}]},
    {"role": "user", "parts": [{"text": "actually never mind"}]},
]
items = O._to_openai_input(dangling)
check("call dropped, text kept", [(it.get("role") or it.get("type")) for it in items] == ["user", "assistant", "user"])
tail = [
    {"role": "user", "parts": [{"text": "hi"}]},
    {"role": "model", "parts": [{"functionCall": {"name": "x", "args": {}}}]},
]
check("dangling call at tail dropped", [(it.get("role") or it.get("type")) for it in O._to_openai_input(tail)] == ["user"])
partial = [
    {"role": "user", "parts": [{"text": "hi"}]},
    {"role": "model", "parts": [
        {"functionCall": {"name": "a", "args": {}}},
        {"functionCall": {"name": "b", "args": {}}},
    ]},
    {"role": "user", "parts": [{"functionResponse": {"name": "a", "response": {"content": "ra"}}}]},
]
items = O._to_openai_input(partial)
calls = [it for it in items if it.get("type") == "function_call"]
outs = [it for it in items if it.get("type") == "function_call_output"]
check("calls truncated to responses present", len(calls) == 1 and len(outs) == 1)
check("surviving pair still matches", calls[0]["call_id"] == outs[0]["call_id"] and calls[0]["name"] == "a")

print("images:")
img = [{"role": "user", "parts": [
    {"text": "what is this?"},
    {"inlineData": {"mimeType": "image/png", "data": "AAAA"}},
]}]
items = O._to_openai_input(img)
content = items[0]["content"]
check("multimodal content list", [b["type"] for b in content] == ["input_text", "input_image"])
check("data URI (string, not object)", content[1]["image_url"] == "data:image/png;base64,AAAA")

print("response translation:")
resp = {"status": "completed", "output": [
    {"type": "reasoning", "summary": []},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "let me check"}]},
    {"type": "function_call", "call_id": "call_X", "name": "baby", "arguments": '{"action": "log"}'},
]}
g = O._to_gemini_response(resp)
parts = g["candidates"][0]["content"]["parts"]
check("function_call present -> TOOL_CALLS", g["candidates"][0]["finishReason"] == "TOOL_CALLS")
fc = [p for p in parts if "functionCall" in p]
check("function_call -> functionCall", fc and fc[0]["functionCall"] == {"name": "baby", "args": {"action": "log"}})
check("reasoning item skipped", len(parts) == 2)
check("text extractable for reply", any(p.get("text") == "let me check" for p in parts))
check("completed text -> STOP", O._to_gemini_response({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]})["candidates"][0]["finishReason"] == "STOP")
check("incomplete max_output_tokens -> MAX_TOKENS",
      O._to_gemini_response({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                             "output": [{"type": "message", "content": [{"type": "output_text", "text": "trunc"}]}]})["candidates"][0]["finishReason"] == "MAX_TOKENS")
bad = O._to_gemini_response({"status": "completed", "output": [
    {"type": "function_call", "call_id": "c", "name": "x", "arguments": "{not json"}]})
check("bad-JSON arguments -> empty args", bad["candidates"][0]["content"]["parts"][0]["functionCall"]["args"] == {})
check("empty output -> None", O._to_gemini_response({"status": "completed", "output": []}) is None)
check("reasoning-only output -> None", O._to_gemini_response({"status": "completed", "output": [{"type": "reasoning"}]}) is None)

print("dispatch routes gpt-* to call_openai (and other ids do NOT):")
import asyncio  # noqa: E402

from hal_orchestrator.services import gemini as GM  # noqa: E402

HIST = [{"role": "user", "parts": [{"text": "hi"}]}]


async def _route(model):
    seen = {}

    async def fake_call_openai(client, settings, history, tools, system, m, *a, **k):
        seen["openai"] = m
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    async def fake_native(client, settings, history, tools, system, m, *a, **k):
        seen["native"] = m
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    orig_openai, orig_native = O.call_openai, GM._call_gemini_native
    O.call_openai = fake_call_openai
    GM._call_gemini_native = fake_native
    try:
        await GM._dispatch_model(None, None, HIST, None, None, model, 1, None, None, is_primary=True)
    finally:
        O.call_openai, GM._call_gemini_native = orig_openai, orig_native
    return seen


s1 = asyncio.run(_route("gpt-5.6-luna"))
check("gpt-5.6-luna -> call_openai", s1.get("openai") == "gpt-5.6-luna" and "native" not in s1)
s2 = asyncio.run(_route("gemini-3.6-flash"))
check("gemini-* -> native (not OpenAI)", s2.get("native") == "gemini-3.6-flash" and "openai" not in s2)
blocky = [{"role": "user", "parts": [{"text": "hi"}]},
          {"role": "model", "parts": [{"_claude_block": {"type": "thinking"}}, {"text": "t"}]}]


async def _route_hist():
    seen = {}

    async def fake_call_openai(client, settings, history, tools, system, m, *a, **k):
        seen["history"] = history
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    orig = O.call_openai
    O.call_openai = fake_call_openai
    try:
        await GM._dispatch_model(None, None, blocky, None, None, "gpt-5.6-luna", 1, None, None, is_primary=True)
    finally:
        O.call_openai = orig
    return seen["history"]


h = asyncio.run(_route_hist())
check("claude blocks stripped before OpenAI even as primary",
      all("_claude_block" not in p for t in h for p in t["parts"]))

print("effort mapping:")
check("MAX->xhigh", O._effort_from_level("MAX") == "xhigh")
check("HIGH->high", O._effort_from_level("HIGH") == "high")
check("MEDIUM->medium", O._effort_from_level("MEDIUM") == "medium")
check("MINIMAL->none", O._effort_from_level("MINIMAL") == "none")
check("unknown->None", O._effort_from_level("") is None)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
