"""Multi-turn PERSONA evals — a simulated brand-new user talks to the real HAL.

Where the scenario suite (run.py) tests single turns, this drives whole
first-contact CONVERSATIONS: an LLM roleplays a specific person who just heard
about HAL (and knows ONLY what the landing page says), texts the real
/api/message pipeline, reacts to whatever HAL replies, and keeps going through
the scenario's timed "beats" (a feed 90 minutes later, a nap, a question). A
blind judge then grades the full transcript + tool trace against the
scenario's rubric and the onboarding contract (value-first, question budget,
no feature dumps, never fake a log).

Usage:
    uv run python evals/persona.py --model gpt-5.6-luna \
        --scenarios 'evals/personas/*.yaml' --out evals/persona_results.json \
        [--db postgresql+asyncpg://user@localhost:5432/hal_evals]

Writes one JSON record per scenario (transcript, per-turn tool calls, judge
grade) plus a human-readable transcript dump next to --out.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))

import httpx
from evals.harness import EVAL_DB_URL, EvalHarness, prepare_env
from evals.judge import ANTHROPIC_URL, ANTHROPIC_VERSION, load_api_key

# Persona + judge default to OpenAI models: the Anthropic key on the Railway
# service has no API credits right now (checked 2026-07-18), while the OpenAI
# key funds the candidate anyway. The judge deliberately differs from the
# gpt-5.6-luna candidate to avoid same-model self-preference.
PERSONA_MODEL = os.environ.get("EVAL_PERSONA_MODEL", "gpt-5.4-mini")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.6-sol")
JUDGE_EFFORT = os.environ.get("EVAL_JUDGE_EFFORT", "high")
MAX_TURNS_DEFAULT = 10
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

PERSONA_SYSTEM = """\
You are roleplaying a REAL person texting a phone number for the first time.
Stay completely in character. You are NOT an assistant here — you are the
customer, with a life, a baby, and very little patience.

CHARACTER SHEET:
{persona}

WHAT YOU KNOW ABOUT THIS SERVICE (and NOTHING more): you saw a webpage that
said "The baby log that lives in your group chat. Text feeds, naps, diapers
the way you'd text your partner. HAL keeps one record for everyone — parents,
nanny, grandma. No app." You do NOT know what it can actually do, what its
features are called, or how any of it works. If HAL mentions something you
don't understand, react like a real person would (ask, ignore, or shrug).

HOW TO TEXT:
- Write ONLY your next text message — no narration, no quotes, no stage
  directions. One message (you may use 2 short lines at most).
- Text like a real exhausted parent: short, lowercase is fine, typos are fine,
  the way your character sheet describes.
- React to what HAL actually said last. Answer its question if you'd plausibly
  answer it; be confused if it was confusing; be annoyed if it was long or
  pushy. Never invent details that contradict your character sheet.
- If HAL's last message needs no reply AND you have nothing new to say, or the
  conversation reached a natural stopping point, reply with exactly: [DONE]

THIS TURN'S SITUATION (what just happened in your life / why you're texting):
{cue}"""

JUDGE_SYSTEM = """\
You grade one complete FIRST-CONTACT conversation between HAL (a baby-log
assistant that lives in iMessage) and a brand-new user, against the product's
onboarding contract and the scenario's specific rubric. You see every user
message, every HAL reply, and the tools HAL actually called each turn (the
ground truth — a "logged ✅" with no baby log call is a FABRICATION).

The onboarding contract (from the product's design doc):
- VALUE FIRST: a loggable event or real question in the user's message gets
  handled before/alongside any setup ask. Never "let me set you up first."
- QUESTION BUDGET: at most 3 setup questions across the WHOLE conversation
  (baby name+age, city, the user's own name — woven, optional), ONE per
  message. Never re-ask something already given.
- NO FEATURE DUMPS: no capability tours, no Google/calendar pitches, no bullet
  lists of what HAL can do.
- NEVER FAKE: "logged" claims must be backed by a baby(action=log) call that
  turn; ambiguous times get a confirm-back, not a guess; counts must match
  enumerated lists. NOTE two grounded side effects you can't see as separate
  calls: baby(action=log) AUTO-SETS standing reminders (wind-down before the
  predicted nap, bottle-prep before the predicted feed) and returns the
  updated forecast in its result — a reply mentioning those right after a log
  call is grounded, not fabricated.
- TONE: warm, brief, texts like a person — not a form, not a clipboard.
- The forecast/digest moments should feel like a payoff, with honest
  uncertainty while data is sparse.

Grade the WHOLE conversation:
- pass: a real parent would keep using this — contract respected, scenario
  goal achieved, nothing fabricated.
- partial: it basically worked but something would erode trust (an extra
  setup question, a missed ack, bloat, a weak moment at the payoff).
- fail: contract broken in a way that loses the household (fabricated log,
  interrogation instead of value, feature dump, wrong/confusing handling of
  the scenario's core situation).

Be strict about fabrication and question budget; be fair about wording."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": ["pass", "partial", "fail"]},
        "reason": {"type": "string"},
        "value_first_ok": {"type": "boolean"},
        "question_budget_ok": {"type": "boolean"},
        "no_feature_dump": {"type": "boolean"},
        "no_fake_logging": {"type": "boolean"},
        "scenario_goal_met": {"type": "boolean"},
        "best_moment": {"type": "string"},
        "worst_moment": {"type": "string"},
    },
    "required": [
        "grade", "reason", "value_first_ok", "question_budget_ok",
        "no_feature_dump", "no_fake_logging", "scenario_goal_met",
        "best_moment", "worst_moment",
    ],
    "additionalProperties": False,
}


async def _llm(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system: str,
    user: str,
    schema: dict | None = None,
    effort: str | None = None,
    max_tokens: int = 8192,
) -> str:
    """One system+user call, routed by model prefix: claude-* → Anthropic
    (api key arg), anything else → OpenAI chat completions (OPENAI_API_KEY
    from env). Returns the text; raises RuntimeError after retries."""
    if model.startswith("claude"):
        url = ANTHROPIC_URL
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        output_config: dict = {}
        if effort:
            output_config["effort"] = effort
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            body["output_config"] = output_config
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
    else:
        url = OPENAI_URL
        body = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if effort:
            # OpenAI's scale differs from Anthropic's; cap at what chat
            # completions accepts.
            body["reasoning_effort"] = {"xhigh": "high"}.get(effort, effort)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }
        headers = {
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}",
            "content-type": "application/json",
        }

    last = "unknown"
    for attempt in range(3):
        try:
            resp = await client.post(url, headers=headers, json=body, timeout=240)
            if resp.status_code == 200:
                data = resp.json()
                if url == ANTHROPIC_URL:
                    return "".join(
                        b.get("text", "")
                        for b in data.get("content", [])
                        if b.get("type") == "text"
                    )
                return data["choices"][0]["message"]["content"] or ""
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code in (429, 500, 503, 529) and attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
                continue
            break
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError(f"llm call failed ({model}): {last}")


def _transcript_text(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        who = t.get("speaker", "USER")
        where = f" in {t['where']}" if t.get("where") == "group" else ""
        lines.append(f"[{t['at_local']}{where}] {who}: {t['user']}")
        reply = t["reply"] or "[stayed silent]"
        lines.append(f"[{t['at_local']}] HAL: {reply}")
        for c in t["tools"]:
            call = f"    tool: {c['tool']}({json.dumps(c['args'], default=str)[:160]})"
            if c.get("result"):
                call += f" -> {c['result'][:220]}"
            lines.append(call)
    return "\n".join(lines)


async def next_persona_message(
    client: httpx.AsyncClient,
    api_key: str,
    persona: str,
    cue: str,
    turns: list[dict],
) -> str:
    convo = "\n".join(
        f"{'YOU' if r == 'user' else 'HAL'}: {txt}"
        for t in turns
        for r, txt in (("user", t["user"]), ("hal", t["reply"] or "[no reply]"))
    )
    prompt = (
        "CONVERSATION SO FAR (YOU = your texts):\n"
        + (convo or "(you haven't texted yet)")
        + "\n\nWrite your next text message now."
    )
    system = PERSONA_SYSTEM.format(persona=persona.strip(), cue=cue.strip())
    text = await _llm(
        client, api_key, PERSONA_MODEL, system, prompt, effort="low",
        max_tokens=2048,
    )
    return text.strip().strip('"')


async def seed_blank(harness: EvalHarness, scenario: dict) -> None:
    """Persona scenarios start from a BLANK world (a brand-new silo) — unlike
    harness.seed, which creates an onboarded profile. Optional seeds still
    apply via the same shapes when a scenario provides them."""
    from sqlalchemy import text

    async with harness._session_factory() as session:
        tables = (
            await session.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename LIKE 'hal_%'"
                )
            )
        ).scalars().all()
        await session.execute(text("TRUNCATE " + ", ".join(tables) + " CASCADE"))
        await session.commit()
    if scenario.get("seed"):
        await harness.seed(scenario)  # rare: scenarios that start mid-life


async def run_scenario(
    harness: EvalHarness,
    client: httpx.AsyncClient,
    api_key: str,
    scenario: dict,
    model: str,
) -> dict:
    await seed_blank(harness, scenario)

    persona = scenario["persona"]
    beats = list(scenario.get("beats") or [])
    max_turns = int(scenario.get("max_turns") or MAX_TURNS_DEFAULT)
    now = datetime.fromisoformat(scenario["now"])
    turns: list[dict] = []
    errors: list[str] = []

    # Conversation context — a beat's `context` (silo/sender/is_group/
    # group_name) switches it and it PERSISTS (e.g. the parent moves from
    # their DM into the family group; a second caregiver takes over via a
    # beat-level `persona`). Speaker label follows the active persona.
    ctx = {
        "silo": scenario["silo"],
        "sender": scenario.get("sender"),
        "is_group": bool(scenario.get("is_group")),
        "group_name": scenario.get("group_name"),
    }
    active_persona = persona
    speaker = scenario.get("speaker", "USER")

    user_msg = scenario.get("opening") or await next_persona_message(
        client, api_key, active_persona,
        scenario.get("opening_cue", "Send your first text."), turns,
    )
    pending_event: dict | None = None

    for turn_i in range(max_turns):
        turn_scenario = {
            **scenario,
            **{k: v for k, v in ctx.items() if v is not None or k == "sender"},
            "message": user_msg,
            "now": now.isoformat(),
        }
        # An event beat posts a bridge-style group lifecycle event instead of
        # a persona message (member added/removed).
        turn_scenario.pop("group_event", None)
        turn_scenario.pop("group_event_target", None)
        if pending_event:
            turn_scenario.update(pending_event)
            turn_scenario["message"] = ""
        result = await harness.run_turn(turn_scenario, model)
        if result.error:
            errors.append(f"turn {turn_i}: {result.error}")
        turns.append(
            {
                "at_local": now.strftime("%a %-I:%M %p"),
                "speaker": "[event]" if pending_event else speaker,
                "where": "group" if ctx["is_group"] else "dm",
                "user": (
                    f"[{pending_event['group_event']} event]"
                    if pending_event
                    else user_msg
                ),
                "reply": result.reply,
                "silent": result.silent,
                "tools": result.tool_trace,
                "error": result.error,
            }
        )
        pending_event = None
        if result.error:
            break

        # Next beat: advance the clock, apply any context/persona switch, and
        # hand the persona its next cue. A [DONE] with beats REMAINING means
        # the character simply went quiet until the next life event — consume
        # the next beat instead of ending the scenario (otherwise one "nothing
        # to add" reply skips every later feed/nap the scenario planned).
        user_msg = None
        while True:
            if beats:
                beat = beats.pop(0)
                now = now + timedelta(minutes=int(beat.get("after_min") or 2))
                cue = beat.get("cue") or "Continue the conversation naturally."
                if beat.get("context"):
                    ctx.update(beat["context"])
                if beat.get("persona"):
                    active_persona = beat["persona"]
                if beat.get("speaker"):
                    speaker = beat["speaker"]
                if beat.get("event"):
                    pending_event = {"group_event": beat["event"]}
                    if beat.get("event_target"):
                        pending_event["group_event_target"] = beat["event_target"]
                    user_msg = ""
                    break
            else:
                now = now + timedelta(minutes=2)
                cue = (
                    "You have nothing new happening. If HAL's last message "
                    "deserves a quick natural reply, send it; otherwise reply "
                    "[DONE]."
                )
            try:
                candidate = await next_persona_message(
                    client, api_key, active_persona, cue, turns
                )
            except RuntimeError as exc:
                errors.append(f"persona: {exc}")
                break
            if not candidate.strip().upper().startswith("[DONE]"):
                user_msg = candidate
                break
            if not beats:
                break
        if user_msg is None:
            break

    # ---- judge ----------------------------------------------------------- #
    seed_note = ""
    if scenario.get("seed"):
        seed_note = (
            "PRE-EXISTING CONTEXT (seeded BEFORE the conversation — HAL "
            "already knows this; using it is grounded, not invented):\n"
            + json.dumps(scenario["seed"], indent=1, default=str)[:1200]
            + "\n\n"
        )
    judge_prompt = (
        f"SCENARIO: {scenario.get('description', scenario['id'])}\n\n"
        f"SCENARIO RUBRIC (what specifically must go right here):\n"
        f"{scenario.get('rubric', '(none)').strip()}\n\n"
        + seed_note
        + f"FULL TRANSCRIPT WITH TOOL GROUND TRUTH:\n{_transcript_text(turns)}"
    )
    try:
        raw = await _llm(
            client, api_key, JUDGE_MODEL, JUDGE_SYSTEM, judge_prompt,
            schema=JUDGE_SCHEMA, effort=JUDGE_EFFORT, max_tokens=16384,
        )
        s = raw.strip()
        grade = json.loads(s[s.find("{"): s.rfind("}") + 1])
    except Exception as exc:  # noqa: BLE001
        grade = {"grade": "na", "reason": f"judge error: {exc}"[:300]}

    return {
        "scenario_id": scenario["id"],
        "model": model,
        "turns": turns,
        "n_turns": len(turns),
        "errors": errors,
        "judge": grade,
    }


def _freeze_routes_clock(harness: EvalHarness) -> None:
    """Multi-turn conversations span simulated hours (and scenarios are dated
    days from the real clock), so the SCENARIO clock must rule everywhere the
    turn touches wall time — not just the prompt module the harness freezes.
    Without this, tools/baby rejects scenario-time logs as 'in the future'
    and HAL truthfully reports a broken tracker clock (observed in smoke)."""
    from datetime import datetime as real_dt

    import hal_orchestrator.routes.message as msg_mod
    import hal_orchestrator.services.baby_card as card_mod
    import hal_orchestrator.tools.baby as baby_tool_mod

    class _Frozen(real_dt):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            frozen = harness._frozen_now
            if frozen is None:
                return real_dt.now(tz)
            if tz is not None:
                return frozen.astimezone(tz)
            return frozen.replace(tzinfo=None)

    for mod in (msg_mod, baby_tool_mod, card_mod):
        mod.datetime = _Frozen


def _capture_tool_results(harness: EvalHarness) -> None:
    """Attach each tool's RESULT to its trace entry so the judge can verify
    claims grounded in tool output (auto-set reminders, forecast lines, CSV
    exports) instead of guessing from call args alone. Patches both the
    registry and routes.message's import-time reference."""
    import hal_orchestrator.routes.message as msg_mod
    import hal_orchestrator.tools.registry as reg

    orig = reg.execute_tool

    async def wrapped(name, args, ctx):
        result = await orig(name, args, ctx)
        for entry in reversed(harness._trace):
            if entry.get("tool") == name and "result" not in entry:
                entry["result"] = str(result)[:400]
                break
        return result

    reg.execute_tool = wrapped
    msg_mod.execute_tool = wrapped


def load_scenarios(pattern: str) -> list[dict]:
    import yaml

    out = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            doc = yaml.safe_load(f)
        if doc and doc.get("id"):
            out.append(doc)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="candidate model for HAL")
    ap.add_argument("--scenarios", default="evals/personas/*.yaml")
    ap.add_argument("--out", default="evals/persona_results.json")
    ap.add_argument("--db", default=EVAL_DB_URL)
    ap.add_argument("--only", default="", help="comma-separated scenario ids")
    args = ap.parse_args()

    # API keys for candidate + persona/judge (pull from railway if missing).
    from evals.run import ensure_api_keys

    ensure_api_keys()
    prepare_env(args.db)
    api_key = load_api_key()

    scenarios = load_scenarios(args.scenarios)
    if args.only:
        keep = {s.strip() for s in args.only.split(",")}
        scenarios = [s for s in scenarios if s["id"] in keep]
    if not scenarios:
        print("no scenarios matched", file=sys.stderr)
        return 2

    harness = EvalHarness()
    await harness.start()
    _freeze_routes_clock(harness)
    _capture_tool_results(harness)
    records = []
    try:
        async with httpx.AsyncClient() as client:
            for sc in scenarios:
                print(f"=== {sc['id']} ===")
                rec = await run_scenario(harness, client, api_key, sc, args.model)
                g = rec["judge"]
                print(
                    f"  -> {g.get('grade', '?')} ({rec['n_turns']} turns) — "
                    f"{g.get('reason', '')[:110]}"
                )
                records.append(rec)
                with open(args.out, "w") as f:
                    json.dump(records, f, indent=2, default=str)
    finally:
        await harness.stop()

    # Readable transcripts beside the JSON.
    md_path = args.out.rsplit(".", 1)[0] + ".md"
    with open(md_path, "w") as f:
        for rec in records:
            g = rec["judge"]
            f.write(f"## {rec['scenario_id']} — {g.get('grade', '?')}\n\n")
            f.write(f"**Judge:** {g.get('reason', '')}\n\n")
            for k in (
                "value_first_ok", "question_budget_ok", "no_feature_dump",
                "no_fake_logging", "scenario_goal_met",
            ):
                if k in g:
                    f.write(f"- {k}: {'✅' if g[k] else '❌'}\n")
            if g.get("worst_moment"):
                f.write(f"- worst: {g['worst_moment']}\n")
            f.write("\n```\n")
            f.write(_transcript_text(rec["turns"]))
            f.write("\n```\n\n")
    counts: dict[str, int] = {}
    for r in records:
        gr = r["judge"].get("grade", "na")
        counts[gr] = counts.get(gr, 0) + 1
    print(f"\nWrote {args.out} + {md_path}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
