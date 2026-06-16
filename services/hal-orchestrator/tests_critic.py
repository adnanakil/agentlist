"""Tests for the self-critique pass: gate, JSON parsing, fact extraction, and
the revise/keep decision with a stubbed model.

Run: python3 services/hal-orchestrator/tests_critic.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import critic

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


ITINERARY = """Here is how we can time it around Bazzy's feeds and naps:
- 10:30 AM: Feed Bazzy at home.
- 11:15 AM: Leave home and take the C train uptown.
- 11:45 AM: Arrive at the museum; Bazzy falls asleep in the stroller as you explore.
- 1:30 PM: Feed at the museum cafe.
- 2:15 PM: Get your facial nearby.
- 4:30 PM: Feed Bazzy back at home."""

print("gate:")
check("timed itinerary -> critique", critic.should_critique("plan my museum day", ITINERARY, 5, False))
check("chit-chat -> skip", not critic.should_critique("he napped", "Logged his nap at 2pm!", 1, False))
check("trivial -> skip", not critic.should_critique("2+2?", "4", 0, False))
check("short ack -> skip", not critic.should_critique("thanks", "anytime!", 0, False))
check(
    "researched plan request -> critique",
    critic.should_critique("what should I do tomorrow", "Here are options. " * 30, 3, False),
)
check(
    "long fact-check, no plan request, no clocks -> skip",
    not critic.should_critique("is this true?", "Yes this is accurate because " * 30, 4, False),
)

print("_parse_json:")
check("plain", critic._parse_json('{"flawed": true, "issues": ["x"]}')["flawed"] is True)
check("fenced", critic._parse_json('```json\n{"flawed": false}\n```')["flawed"] is False)
check("garbage -> {}", critic._parse_json("nope") == {})

print("_gathered_facts (pulls tool results, not the template):")
history = [
    {"role": "user", "parts": [{"text": "plan my day"}]},
    {"role": "model", "parts": [{"functionCall": {"name": "get_weather", "args": {}}}]},
    {"role": "user", "parts": [{"functionResponse": {"name": "get_weather", "response": {"content": "Rain timing: 12am-5am — otherwise dry."}}}]},
    {"role": "model", "parts": [{"text": "the plan"}]},
]
facts = critic._gathered_facts(history)
check("extracted the weather fact", any("Rain timing" in f for f in facts), facts)
check("did not include model text", not any("the plan" in f for f in facts))


# --- revise/keep logic with a stubbed call_gemini ---
print("critique_and_revise branches:")


def stub_resp(obj_text):
    return {"candidates": [{"content": {"parts": [{"text": obj_text}]}}]}


async def run():
    orig = critic.call_gemini

    async def fake_caught(*a, **k):
        return stub_resp('{"flawed": true, "issues": ["baby asleep during museum"], "change_summary": "kept him awake for the museum, asleep for the facial", "revised_reply": "Totally different corrected plan: keep him awake for the museum, then time his nap to land during your 2pm facial so you are hands-free. Leave at 9, museum 10-12, nap 1-2 during the facial."}')

    async def fake_clean(*a, **k):
        return stub_resp('{"flawed": false, "issues": [], "revised_reply": ""}')

    async def fake_flagged_norewrite(*a, **k):
        return stub_resp('{"flawed": true, "issues": ["confidence too high"], "revised_reply": ""}')

    # The bug from the field: critic "fixes" by renumbering naps — near-identical
    # text. Must be suppressed (cosmetic), not sent as a "Quick fix".
    _orig_plan = (
        "To keep him awake for his 1:00 PM appointment, get his first nap out of "
        "the way beforehand.\n11:32 AM - Nap 1 (45 mins)\n12:17 PM - Wake up\n"
        "12:25 PM - Feed\n1:00 PM - Appointment\n2:24 PM - Nap 2 (45 mins)\n3:15 PM - Feed"
    )
    _cosmetic_revision = _orig_plan.replace("first nap", "next nap").replace(
        "Nap 1", "Nap 2"
    ).replace("Nap 2 (45 mins)\n3:15", "Nap 3 (45 mins)\n3:15")

    async def fake_cosmetic(*a, **k):
        import json as _j
        return stub_resp(_j.dumps({
            "flawed": True,
            "issues": ["nap numbering"],
            "change_summary": "renumbered the naps",
            "revised_reply": _cosmetic_revision,
        }))

    async def fake_none(*a, **k):
        return None

    ctx = _Ctx()
    try:
        critic.call_gemini = fake_caught
        reply, rep = await critic.critique_and_revise(ctx, [], "plan", "ORIG PLAN")
        check("caught -> revised reply used", reply.startswith("Totally different") and rep["caught"] is True)
        check("caught -> issues surfaced", rep["issues"] == ["baby asleep during museum"])
        check("caught -> change summary surfaced", rep.get("summary", "").startswith("kept him awake"))

        critic.call_gemini = fake_cosmetic
        reply, rep = await critic.critique_and_revise(ctx, [], "plan", _orig_plan)
        check("cosmetic renumber -> SUPPRESSED (not caught)", rep["caught"] is False and rep.get("cosmetic") is True)
        check("cosmetic renumber -> original kept", reply == _orig_plan)

        critic.call_gemini = fake_clean
        reply, rep = await critic.critique_and_revise(ctx, [], "plan", "ORIG PLAN")
        check("clean -> original kept", reply == "ORIG PLAN" and rep["caught"] is False)

        critic.call_gemini = fake_flagged_norewrite
        reply, rep = await critic.critique_and_revise(ctx, [], "plan", "ORIG PLAN")
        check("flagged but no rewrite -> keep original, issues still surfaced",
              reply == "ORIG PLAN" and rep["caught"] is False and rep["issues"] == ["confidence too high"])

        critic.call_gemini = fake_none
        reply, rep = await critic.critique_and_revise(ctx, [], "plan", "ORIG PLAN")
        check("model failure -> safe passthrough", reply == "ORIG PLAN" and rep["caught"] is False)
    finally:
        critic.call_gemini = orig


class _S:
    gemini_model = "x"
    gemini_background_model = "x"  # critic runs on the background model


class _Ctx:
    """Minimal ToolContext stand-in — the stubbed call_gemini returns a verdict
    with no tool calls, so the verification loop never executes a tool."""
    phone = "+1"
    settings = _S()
    http_client = None


asyncio.run(run())

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
