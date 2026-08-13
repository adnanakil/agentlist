#!/usr/bin/env python3
"""Schema check for HAL eval scenarios. Run: uv run python evals/scenarios/validate.py

Contract shared with evals/harness.py: external tools are stubbed from
tool_fixtures (un-fixtured external tools return an error string); internal
tools run real against seeded local state; current_time derives from `now`.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))

CATEGORIES = {
    "baby-logging",
    "reminders-time",
    "group-restraint",
    "proactive-judgment",
    "fact-check-links",
    "multi-tool-errands",
    "memory-recall",
    "tone-format",
}

# Tools that reach outside the harness — a scenario asserting one of these in
# tools_called MUST provide a deterministic fixture for it.
EXTERNAL_TOOLS = {
    "get_weather", "web_search", "web_fetch", "browser", "places",
    "travel_time", "sports_score", "nyc_events", "resy", "parking",
    "google_calendar", "google_gmail", "google_auth", "image_edit", "delegate",
}
# Tools that run real against seeded local state — fixturing them would mask
# the behavior under test.
INTERNAL_TOOLS = {
    "baby", "memory", "set_reminder", "profile", "contacts", "recall_history",
    "current_time", "group_quiet", "watch", "schedule", "trip", "helpful_mode",
    "send_message", "skill",
}
KNOWN_TOOLS = EXTERNAL_TOOLS | INTERNAL_TOOLS

BABY_KINDS = {"feed", "nap_start", "wake", "bedtime", "tummy_time", "diaper", "note"}

REQUIRED = ["id", "category", "description", "silo", "is_group", "sender", "now",
            "message", "internal", "expect"]


def fail(errors: list[str], sid: str, msg: str) -> None:
    errors.append(f"{sid}: {msg}")


def check_file(path: str, errors: list[str]) -> list[str]:
    """A file holds one scenario doc or a list of them (same contract as
    run.py). Returns the categories of the valid scenarios found."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    docs = doc if isinstance(doc, list) else [doc]
    fname = os.path.splitext(os.path.basename(path))[0]
    cats = []
    for i, sc in enumerate(docs):
        label = fname if len(docs) == 1 else f"{fname}[{i}]"
        cat = check_scenario(sc, label, len(docs) == 1, errors)
        if cat:
            cats.append(cat)
    return cats


def check_scenario(
    sc: dict, sid: str, standalone: bool, errors: list[str]
) -> str | None:
    if not isinstance(sc, dict):
        fail(errors, sid, "scenario doc is not a mapping")
        return None
    for field in REQUIRED:
        if field not in sc:
            fail(errors, sid, f"missing required field '{field}'")
            return None

    # Single-doc files keep the id==filename rule; list files carry ids inline.
    if standalone and sc["id"] != sid:
        fail(errors, sid, f"id '{sc['id']}' != filename")
    if sc["category"] not in CATEGORIES:
        fail(errors, sid, f"unknown category '{sc['category']}'")

    is_group_silo = str(sc["silo"]).startswith("chat")
    if bool(sc["is_group"]) != is_group_silo:
        fail(errors, sid, "is_group inconsistent with silo prefix")
    if not str(sc["sender"]).startswith("+"):
        fail(errors, sid, "sender must be a phone number")

    try:
        dt = datetime.fromisoformat(str(sc["now"]))
        if dt.tzinfo is None:
            fail(errors, sid, "'now' must carry a UTC offset")
    except ValueError:
        fail(errors, sid, f"unparseable now: {sc['now']}")

    if not str(sc["message"]).strip():
        fail(errors, sid, "empty message")

    seed = sc.get("seed") or {}
    for turn in seed.get("history") or []:
        if turn.get("role") not in ("user", "model"):
            fail(errors, sid, f"history role must be user|model, got {turn.get('role')}")
        if not str(turn.get("text", "")).strip():
            fail(errors, sid, "history turn with empty text")
    for ev in seed.get("baby_events") or []:
        if ev.get("kind") not in BABY_KINDS:
            fail(errors, sid, f"unknown baby event kind '{ev.get('kind')}'")
        try:
            datetime.fromisoformat(str(ev.get("at", "")))
        except ValueError:
            fail(errors, sid, f"unparseable baby event time: {ev.get('at')}")

    fixtures = sc.get("tool_fixtures") or {}
    for name in fixtures:
        if name not in KNOWN_TOOLS:
            fail(errors, sid, f"fixture for unknown tool '{name}'")
        if name in INTERNAL_TOOLS:
            fail(errors, sid, f"fixture stubs INTERNAL tool '{name}' — seed state instead")

    exp = sc["expect"]
    if not str(exp.get("reply_should", "")).strip():
        fail(errors, sid, "expect.reply_should is required")
    if not isinstance(exp.get("silent_expected", False), bool):
        fail(errors, sid, "expect.silent_expected must be a bool")
    for key in ("tools_called", "tools_absent"):
        for name in exp.get(key) or []:
            if name not in KNOWN_TOOLS:
                fail(errors, sid, f"expect.{key} references unknown tool '{name}'")
    for name in exp.get("tools_called") or []:
        if name in EXTERNAL_TOOLS and name not in fixtures:
            fail(errors, sid, f"external tool '{name}' asserted but has no fixture")
    for name, frag in (exp.get("args_match") or {}).items():
        if name not in KNOWN_TOOLS:
            fail(errors, sid, f"args_match references unknown tool '{name}'")
        if name not in (exp.get("tools_called") or []):
            fail(errors, sid, f"args_match on '{name}' without asserting it in tools_called")
        if not isinstance(frag, dict):
            fail(errors, sid, f"args_match['{name}'] must be a dict")
    if exp.get("silent_expected") and exp.get("tools_called"):
        # A silence scenario may still allow tool use, but asserting calls AND
        # silence is usually a contradiction worth flagging.
        fail(errors, sid, "silent_expected with required tools_called — check intent")

    return sc["category"]


def main() -> int:
    # Underscore-prefixed YAMLs are harness-internal smoke fixtures, not corpus.
    files = sorted(
        f for f in os.listdir(HERE) if f.endswith(".yaml") and not f.startswith("_")
    )
    if not files:
        print("no scenario YAMLs found")
        return 1
    errors: list[str] = []
    counts: dict[str, int] = {}
    total = 0
    for name in files:
        for cat in check_file(os.path.join(HERE, name), errors):
            counts[cat] = counts.get(cat, 0) + 1
            total += 1
    print(f"{total} scenarios")
    for cat in sorted(counts):
        print(f"  {cat}: {counts[cat]}")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  FAIL {e}")
        return 1
    print("all valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
