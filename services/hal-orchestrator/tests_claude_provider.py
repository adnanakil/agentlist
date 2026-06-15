"""Tests for the Claude provider shim's pure translation logic (no API).

Run: python3 services/hal-orchestrator/tests_claude_provider.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import claude_provider as C

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("tools translation:")
tools = [{"function_declarations": [
    {"name": "baby", "description": "track", "parameters": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
    {"name": "get_weather", "description": "wx", "parameters": {"type": "object", "properties": {}}},
]}]
at = C._to_anthropic_tools(tools)
check("count", len(at) == 2)
check("shape", all("input_schema" in t and "name" in t and "description" in t for t in at))
check("schema carried", at[0]["input_schema"]["required"] == ["action"])

print("multi-turn round-trip (claude-native turn):")
history = [
    {"role": "user", "parts": [{"text": "is it raining?"}]},
    {"role": "model", "parts": [
        {"_claude_block": {"type": "thinking", "thinking": "hmm", "signature": "SIG"}},
        {"text": "Checking."},
        {"functionCall": {"name": "get_weather", "args": {"location": "NYC"}},
         "_claude_block": {"type": "tool_use", "id": "toolu_A", "name": "get_weather", "input": {"location": "NYC"}}},
    ]},
    {"role": "user", "parts": [{"functionResponse": {"name": "get_weather", "response": {"content": "dry"}}}]},
]
msgs = C._to_anthropic_messages(history)
check("roles alternate user/assistant/user", [m["role"] for m in msgs] == ["user", "assistant", "user"])
asst = msgs[1]["content"]
check("thinking replayed raw with signature", asst[0]["type"] == "thinking" and asst[0]["signature"] == "SIG")
tu = [b for b in asst if b["type"] == "tool_use"][0]
tr = [b for b in msgs[2]["content"] if b["type"] == "tool_result"][0]
check("tool_use id == tool_result tool_use_id", tu["id"] == "toolu_A" and tr["tool_use_id"] == "toolu_A")

print("loaded (non-native) history collapses to text-only:")
loaded = [
    {"role": "user", "parts": [{"text": "hi"}]},
    {"role": "model", "parts": [{"functionCall": {"name": "x", "args": {}}}]},  # no _claude_block
    {"role": "user", "parts": [{"functionResponse": {"name": "x", "response": {"content": "r"}}}]},
    {"role": "model", "parts": [{"text": "done"}]},
]
m2 = C._to_anthropic_messages(loaded)
check("collapsed to alternating text-only", [m["role"] for m in m2] == ["user", "assistant"])
check("assistant content is text", m2[1]["content"][0]["type"] == "text" and m2[1]["content"][0]["text"] == "done")

print("image translation:")
img = [{"role": "user", "parts": [{"text": "what is this"}, {"inlineData": {"mimeType": "image/png", "data": "AAA"}}]}]
mi = C._to_anthropic_messages(img)
types = [b["type"] for b in mi[0]["content"]]
check("text + image blocks", types == ["text", "image"])
check("image base64 source", mi[0]["content"][1]["source"]["media_type"] == "image/png")

print("response translation:")
resp = {"stop_reason": "tool_use", "content": [
    {"type": "thinking", "thinking": "t", "signature": "S"},
    {"type": "text", "text": "hello"},
    {"type": "tool_use", "id": "toolu_X", "name": "baby", "input": {"action": "log"}},
]}
g = C._to_gemini_response(resp)
parts = g["candidates"][0]["content"]["parts"]
check("finishReason tool_use -> TOOL_CALLS", g["candidates"][0]["finishReason"] == "TOOL_CALLS")
fc = [p for p in parts if "functionCall" in p]
check("tool_use -> functionCall + stashed id", fc and fc[0]["functionCall"]["name"] == "baby" and fc[0]["_claude_block"]["id"] == "toolu_X")
check("thinking stashed (no text key)", any("_claude_block" in p and "text" not in p and p["_claude_block"]["type"] == "thinking" for p in parts))
check("text extractable for reply", any(p.get("text") == "hello" for p in parts))
check("end_turn -> STOP", C._to_gemini_response({"stop_reason": "end_turn", "content": [{"type": "text", "text": "hi"}]})["candidates"][0]["finishReason"] == "STOP")

print("effort mapping:")
check("HIGH->high", C._effort_from_level("HIGH") == "high")
check("MEDIUM->medium", C._effort_from_level("MEDIUM") == "medium")
check("MINIMAL->low", C._effort_from_level("MINIMAL") == "low")
check("unknown->None", C._effort_from_level("") is None)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
