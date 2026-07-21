"""Day-in-the-life eval for HAL — one CONTINUOUS simulated day on a test silo.

Unlike eval_hal_behavior.py (isolated scenarios, restore between each), this
suite runs a whole compressed day as ONE conversation that carries forward:

  earlier     seed: user lists today's plan (three anchor events)
  [day-brief]        user asks "what's my day looking like?" -> recap all three
  [hb-commute]       heartbeat sees event 1 ~50 min out -> leave-by nudge
  [hb-delivery]      a package lands in the inbox -> surface it
  [hb-delivery-dup]  SAME inbox next tick -> must stay SILENT (identity dedup,
                     mirrored exactly like services/heartbeat._beat)
  [walk-check]       "stroller walk before X?" -> live weather + timing
  [hb-appt]          event 3 ~55 min out -> nudge (no manufactured urgency)
  [hb-appt-dup]      next tick, same calendar -> SILENT
  [recall-lunch]     "what was that place Priya wanted?" -> Khe-Yo, from context
  [reminder-real]    "remind me in 20 min" -> hal_reminders row must exist AND
                     be due 10-40 min in the FUTURE (catches the live AM/PM-slip
                     bug where a "7:22 PM" reminder was stored as 07:22 and
                     fired instantly) — decisive, checked in the DB
  [hb-evening-quiet] nothing going on -> SILENT

Event times are RELATIVE to run time (the day is compressed into one run) and
the event LABELS adapt to the local hour, so a morning run gets standup/lunch/
pediatric checkup while an evening run gets office sync/drinks/pharmacy-close —
HAL should never be asked to believe in a 12:19 AM pediatrician.

SAFE: fictional test silo (+15555550100), snapshot conversation+profile to a
sidecar before touching anything, restore + delete created rows in finally.
If a run is killed mid-way: python scripts/eval_real_day.py --restore

Usage:
  DATABASE_PUBLIC_URL=... HAL_BRIDGE_SECRET=... python scripts/eval_real_day.py [id ...]
Env: DATABASE_URL or DATABASE_PUBLIC_URL, HAL_BRIDGE_SECRET, optional HAL_URL,
     EVAL_SILO (guarded), EVAL_BG_MODEL (heartbeat model; default matches the
     production GEMINI_BACKGROUND_MODEL, gemini-3.6-flash).
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import httpx

URL = os.environ.get("HAL_URL", "https://hal-orchestrator-production.up.railway.app/api/message")
TEST_SILO = "+15555550100"
SILO = os.environ.get("EVAL_SILO", TEST_SILO)
BG_MODEL = os.environ.get("EVAL_BG_MODEL", "gemini-3.6-flash")
ET = ZoneInfo("America/New_York")

TEST_PROFILE_NOTES = (
    "Adnan — Chelsea, Manhattan (NYC, America/New_York). Two adults; 5-month-old "
    "son Bazzy. Works out at Chelsea Piers. Office is in Dumbo, Brooklyn. "
    "Interests: tech, markets, philosophy."
)


def _at(minutes: int) -> str:
    return (datetime.now(ET) + timedelta(minutes=minutes)).strftime("%-I:%M %p")


def _now_line() -> str:
    return datetime.now(ET).strftime("%A, %B %d, %Y at %-I:%M %p %Z") + " — your local time"


# Anchor-event offsets (minutes from run start).
T1, T2, T3 = 50, 190, 320


def _day_shape() -> dict:
    """Three anchor events whose labels stay plausible for the local hour the
    run starts at — a compressed 'day' that begins at 7pm shouldn't contain a
    midnight pediatrician."""
    h = datetime.now(ET).hour
    if h < 14:  # morning/early-afternoon run: the classic day
        return {
            "e1": {"seed": f"standup at {_at(T1)} at the office in Dumbo",
                   "cal": lambda: f"{_at(T1)} Standup — office, Dumbo (Brooklyn)",
                   "kws": ["standup", "dumbo", "leave", "head out", "subway", "train", "traffic"]},
            "e2": {"seed": f"lunch with Priya at {_at(T2)} — she wants to try Khe-Yo, "
                           f"that Laotian place in Tribeca",
                   "cal": lambda: f"{_at(T2)} Lunch w/ Priya — Khe-Yo, Tribeca",
                   "kws": ["priya", "khe-yo", "lunch"]},
            "e3": {"seed": f"Bazzy's pediatrician checkup at {_at(T3)} with Dr. Morales "
                           f"at 156 W 23rd St",
                   "cal": lambda m: f"{_at(m)} Bazzy pediatrician checkup — Dr. Morales, 156 W 23rd St",
                   "kws": ["pediatrician", "checkup", "morales", "appointment", "leave", "23rd"],
                   "walk_ref": "his checkup"},
        }
    return {  # afternoon/evening run: same skills, evening-shaped events
        "e1": {"seed": f"team sync at {_at(T1)} at the office in Dumbo",
               "cal": lambda: f"{_at(T1)} Team sync — office, Dumbo (Brooklyn)",
               "kws": ["sync", "dumbo", "office", "leave", "head out", "subway", "train", "traffic"]},
        "e2": {"seed": f"meeting Priya at {_at(T2)} — she wants to try Khe-Yo, "
                       f"that Laotian place in Tribeca",
               "cal": lambda: f"{_at(T2)} Priya — Khe-Yo, Tribeca",
               "kws": ["priya", "khe-yo"]},
        "e3": {"seed": f"pharmacy pickup for Bazzy at {_at(T3)} — the Duane Reade on "
                       f"W 23rd St (it closes soon after)",
               "cal": lambda m: f"{_at(m)} Pharmacy pickup for Bazzy — Duane Reade, W 23rd St (closes {_at(m + 45)})",
               "kws": ["pharmacy", "duane", "pickup", "23rd", "closes", "leave"],
               "walk_ref": "the pharmacy run"},
    }


SHAPE = _day_shape()


def seed_history() -> list[dict]:
    stamp = datetime.now(ET).strftime("%a %b %-d %-I:%M %p")
    return [
        {"role": "user", "parts": [{"text":
            f"[{stamp}] hey — big day today. {SHAPE['e1']['seed']}, "
            f"{SHAPE['e2']['seed']}, and {SHAPE['e3']['seed']}. "
            f"don't let me miss any of it"}]},
        {"role": "model", "parts": [{"text":
            "On it — all three tracked. I'll keep you posted through the day 👍"}]},
    ]


SEED_FINGERPRINT = "she wants to try Khe-Yo"

NOISE_MAIL = (
    "- [id: 19a001aa11] from The Information — Today in tech (newsletter)\n"
    "- [id: 19a001bb22] from GitHub — Deploy succeeded: web-production (#4922)\n"
    "- [id: 19a001cc33] from Nextdoor — Trending in Chelsea (digest)"
)
DELIVERY_MAIL = (
    "- [id: 19a002dd44] from Amazon — Delivered: your package was left at the front "
    "door  (Your stroller rain cover has been delivered. See delivery photo)\n"
    "- [id: 19a002ee55] from USPS Informed Delivery — Your daily mail-scan digest\n"
    "- [id: 19a001aa11] from The Information — Today in tech (newsletter)"
)


def _cal(*events: str) -> str:
    return "Upcoming calendar:\n" + ("\n".join(f"- {e}" for e in events) if events
                                     else "(nothing in the next 2 hours)")


def _gathered(cal: str, mail: str) -> str:
    return (f"Current time — {_now_line()}\n\n{cal}\n\n"
            f"Recent unread email:\n{mail}")


PHASES = [
    {"id": "day-brief", "kind": "user", "label": "the brief",
     "text": lambda: "morning! what's my day looking like?" if datetime.now(ET).hour < 14
                     else "hey, what's the rest of my day looking like?",
     "groups": [SHAPE["e1"]["kws"][:3], SHAPE["e2"]["kws"], SHAPE["e3"]["kws"][:4]],
     "want": "recap ALL THREE events from the earlier message (no Google needed — "
             "it's in the conversation)"},

    {"id": "hb-commute", "kind": "hb", "label": "~50 min to event 1 — commute nudge",
     "cal": lambda: _cal(SHAPE["e1"]["cal"]()),
     "mail": lambda: NOISE_MAIL,
     "expect": "alert", "must_mention": SHAPE["e1"]["kws"],
     # If the day-brief already SET a leave-reminder for event 1 (HAL does this
     # unprompted — good!), a heartbeat alert would be a duplicate: silence is
     # then the CORRECT behavior, so accept silent-when-covered.
     "silent_ok_if_reminder": "%dumbo%",
     "want": "CHECK 1: event 1 is close — nudge a leave-by time, UNLESS a "
             "leave-reminder already covers it (then silence is right)"},

    # The two delivery ticks are scored as a PAIR: the delivery must surface
    # EXACTLY ONCE across them (first tick ideal; one tick late acceptable —
    # a stalled/tool-heavy first tick is forced silent by design). Twice =
    # repeat spam; never = over-suppression.
    {"id": "hb-delivery", "kind": "hb", "label": "package lands (tick 1 of 2)",
     "cal": lambda: _cal(SHAPE["e2"]["cal"]()),
     "mail": lambda: DELIVERY_MAIL,
     "expect": "alert",
     "must_mention": ["deliver", "package", "front door", "rain cover", "arrived"],
     "pair": "delivery",
     "want": "CHECK 2: the stroller rain cover was DELIVERED — lead with that; "
             "event 2 is hours off, USPS digest and newsletter are noise"},

    {"id": "hb-delivery-dup", "kind": "hb", "label": "next tick — SAME inbox (tick 2 of 2)",
     "cal": lambda: _cal(SHAPE["e2"]["cal"]()),
     "mail": lambda: DELIVERY_MAIL,
     "expect": "silent",
     "pair": "delivery",
     "must_mention": ["deliver", "package", "front door", "rain cover", "arrived"],
     "want": "identity dedup: across BOTH ticks the delivery is told exactly "
             "once — re-narrating it here (after tick 1 alerted) is the old "
             "24x-repeat bug"},

    {"id": "walk-check", "kind": "user", "label": "stroller walk?",
     "text": lambda: (f"thinking of taking Bazzy out for a stroller walk before "
                      f"{SHAPE['e3'].get('walk_ref', 'the next thing')} — good call?"),
     "groups": [["rain", "weather", "dry", "sunny", "cloud", "°", "degrees",
                 "clear", "shower", "wind", "humid", "warm", "cold", "hot", "mild"]],
     "min_tools": 1,
     "want": "ground the answer in LIVE hourly weather (tool call, not vibes) and "
             "respect the upcoming commitment — a real yes/no with a window"},

    {"id": "hb-appt", "kind": "hb", "label": "~55 min to event 3 — nudge",
     "cal": lambda: _cal(SHAPE["e3"]["cal"](55)),
     "mail": lambda: NOISE_MAIL,
     "expect": "alert", "must_mention": SHAPE["e3"]["kws"],
     # HAL often gets ahead of the script — e.g. it noticed at the delivery
     # tick that the pharmacy closes early and already told the user (and set
     # a reminder). If a PRIOR reply this run covered event 3, silence here is
     # correct, not a miss.
     "ok_if_covered": True,
     "want": "event 3 is ~55 min out — nudge with it and when to head out, "
             "UNLESS an earlier reply already handled it (then silence is right)"},

    {"id": "hb-appt-dup", "kind": "hb", "label": "next tick — same calendar",
     "cal": lambda: _cal(SHAPE["e3"]["cal"](40)),
     "mail": lambda: NOISE_MAIL,
     "expect": "silent",
     "want": "it JUST nudged about event 3 — a second nudge 15 min later is the "
             "repeat-spam failure mode; must stay quiet"},

    {"id": "recall-lunch", "kind": "user", "label": "recall the Priya spot",
     "text": lambda: "what was the name of that place priya wanted again?",
     "groups": [["khe-yo"]],
     "want": "pull Khe-Yo from earlier context — not 'I don't know', not a guess"},

    {"id": "reminder-real", "kind": "user", "label": "reminder must be REAL + future",
     "text": lambda: "remind me to prep bazzy's bottles in 20 minutes",
     "groups": [["remind", "reminder", "ping", "nudge", "20", "min"]],
     "db_reminder": "%bottle%",
     "want": "confirm it AND the hal_reminders row must exist with due_at 10-40 "
             "min in the FUTURE (the live AM/PM-slip bug stored 7:22 PM as 07:22 "
             "and fired instantly — the past-due guard must prevent that)"},

    {"id": "hb-evening-quiet", "kind": "hb", "label": "wind-down — nothing going on",
     "cal": lambda: _cal(),
     "mail": lambda: NOISE_MAIL,
     "expect": "silent",
     "want": "empty calendar + noise inbox + day's items all handled -> silence"},
]

CLEAN = [("hal_turns", "phone"), ("hal_messages", "phone"), ("hal_reminders", "phone"),
         ("hal_cron_jobs", "phone"), ("hal_user_memories", "phone"),
         ("hal_friction_events", "phone")]

SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    ".eval_snap_" + re.sub(r"\D", "", SILO) + ".json")


def _is_quiet(text: str) -> bool:
    return text.strip().strip(".…·•- \t\n") == ""


def _pg_url() -> str:
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    for pre in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(pre):
            url = "postgresql://" + url[len(pre):]
    return url


async def _read_snap(conn):
    c = await conn.fetchrow(
        "SELECT history::text h, message_count mc, summary s, summarized_at_count sc "
        "FROM hal_conversations WHERE phone=$1", SILO)
    p = await conn.fetchrow("SELECT notes FROM hal_user_profiles WHERE phone=$1", SILO)
    return {"h": c["h"], "mc": c["mc"], "s": c["s"], "sc": c["sc"],
            "notes": p["notes"] if p else None} if c else None


async def _restore(conn, snap):
    await conn.execute(
        "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3, "
        "summary=$4, summarized_at_count=$5 WHERE phone=$1",
        SILO, snap["h"], snap["mc"], snap["s"], snap["sc"])
    if snap.get("notes") is not None:
        await conn.execute("UPDATE hal_user_profiles SET notes=$2 WHERE phone=$1",
                           SILO, snap["notes"])


async def _ensure_test_silo(conn):
    if not await conn.fetchrow("SELECT 1 FROM hal_conversations WHERE phone=$1", SILO):
        await conn.execute(
            "INSERT INTO hal_conversations(id, phone, history, message_count, summary, "
            "summarized_at_count) VALUES(gen_random_uuid(), $1, '[]'::jsonb, 0, '', 0)", SILO)
    if not await conn.fetchrow("SELECT 1 FROM hal_user_profiles WHERE phone=$1", SILO):
        await conn.execute(
            "INSERT INTO hal_user_profiles(id, phone, onboarded, notes) "
            "VALUES(gen_random_uuid(), $1, true, $2)", SILO, TEST_PROFILE_NOTES)


async def _guard_live_silo(conn, argv):
    if SILO == TEST_SILO or "--force" in argv:
        return
    busy = await conn.fetchval(
        "SELECT now() - max(created_at) < interval '15 minutes' "
        "FROM hal_messages WHERE phone=$1", SILO)
    if busy:
        await conn.close()
        sys.exit(f"REFUSING: {SILO} had real activity <15 min ago. "
                 f"Use the test silo or --force only if it's idle.")


async def main():
    from hal_orchestrator.services.heartbeat import (
        HEARTBEAT_PROMPT,
        annotate_seen,
        delivery_directive,
        ids_covered_by_alert,
    )

    secret = os.environ.get("HAL_BRIDGE_SECRET")
    pg = _pg_url()
    if not pg or not secret:
        sys.exit("Set DATABASE_PUBLIC_URL (or DATABASE_URL) and HAL_BRIDGE_SECRET")
    argv = sys.argv[1:]
    restore_only = "--restore" in argv
    wanted = {a for a in argv if not a.startswith("--")}
    phases = [p for p in PHASES if not wanted or p["id"] in wanted]

    conn = await asyncpg.connect(pg)

    if restore_only:
        if not os.path.exists(SNAP):
            await conn.close(); sys.exit(f"no sidecar snapshot at {SNAP}")
        with open(SNAP) as f:
            await _restore(conn, json.load(f))
        await conn.close(); print(f"restored buffer from sidecar {SNAP}"); return

    if SILO == TEST_SILO:
        await _ensure_test_silo(conn)
    await _guard_live_silo(conn, argv)

    snap = await _read_snap(conn)
    if snap is None:
        await conn.close(); sys.exit(f"no hal_conversations row for {SILO}")
    if SEED_FINGERPRINT in snap["h"] and os.path.exists(SNAP):
        with open(SNAP) as f:
            await _restore(conn, json.load(f))
        print("⚠️ recovered pre-seed buffer from sidecar (previous run crashed)")
        snap = await _read_snap(conn)
    with open(SNAP, "w") as f:
        json.dump(snap, f)

    # start BEFORE seeding so cleanup also removes the seed's archive rows.
    start = datetime.now(ET)

    # Seed the conversation AND fresh archive rows (the elapsed-gap cue reads
    # hal_messages — without fresh rows the model is told "~2d since the last
    # message" and reasonably concludes the plan is stale).
    seed = seed_history()
    await conn.execute(
        "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3 WHERE phone=$1",
        SILO, json.dumps(seed), len(seed))
    for turn in seed:
        await conn.execute(
            "INSERT INTO hal_messages(id, phone, role, content, created_at) "
            "VALUES(gen_random_uuid(), $1, $2, $3, now())",
            SILO, "user" if turn["role"] == "user" else "assistant",
            turn["parts"][0]["text"])

    seen: dict[str, str] = {}   # mail-id -> ts, mirrors profile hb_seen in _beat
    npass = nfail = 0
    all_replies: list[str] = []       # every non-quiet reply this run (coverage)
    pair_state: dict[str, dict] = {}  # pair name -> {"alerts": n, "first_quiet": bool}
    TRANSIENT = "Sorry, I'm having trouble right now. Please try again."
    shape_kind = "morning" if datetime.now(ET).hour < 14 else "evening"
    print(f"silo {SILO} — {shape_kind}-shaped day starts {start:%-I:%M %p} "
          f"(events at {_at(T1)}, {_at(T2)}, {_at(T3)}; hb model {BG_MODEL})")
    print("=" * 78)

    try:
        async with httpx.AsyncClient(timeout=260) as client:
            for ph in phases:
                pid, label = ph["id"], ph["label"]
                if ph["kind"] == "user":
                    reply, tools = "", 0
                    for attempt in (1, 2):  # one retry on transient model failure
                        try:
                            r = await client.post(
                                URL, headers={"Authorization": f"Bearer {secret}"},
                                json={"phone": SILO, "text": ph["text"]()})
                            d = r.json()
                            reply = (d.get("reply") or "").strip()
                            tools = d.get("tool_calls", 0)
                        except Exception as e:
                            reply, tools = f"[ERROR {e}]", 0
                        if reply != TRANSIENT:
                            break
                        print(f"    [{pid}] transient model failure — retrying once…")
                        await asyncio.sleep(8)
                    rl = reply.lower()
                    if reply and reply != TRANSIENT:
                        all_replies.append(rl)
                    ok = all(any(k in rl for k in grp) for grp in ph.get("groups", []))
                    notes = ["missing: " + "|".join(g) for g in ph.get("groups", [])
                             if not any(k in rl for k in g)]
                    if ph.get("min_tools") and (not isinstance(tools, int) or tools < ph["min_tools"]):
                        ok = False; notes.append(f"tool_calls>={ph['min_tools']} (got {tools})")
                    if ph.get("db_reminder"):
                        row = await conn.fetchrow(
                            "SELECT text, due_at FROM hal_reminders WHERE phone=$1 "
                            "AND text ILIKE $2 AND created_at >= $3", SILO,
                            ph["db_reminder"], start)
                        if not row:
                            ok = False
                            notes.append("db ✗ NO hal_reminders row — claimed without doing")
                        else:
                            due = row["due_at"]
                            mins = (due - datetime.now(due.tzinfo)).total_seconds() / 60
                            if 10 <= mins <= 40:
                                notes.append(f"db ✓ reminder real, due in {mins:.0f} min "
                                             f"({due.astimezone(ET):%-I:%M %p} ET)")
                            else:
                                ok = False
                                notes.append(f"db ✗ due_at {due.astimezone(ET):%-I:%M %p} ET "
                                             f"is {mins:+.0f} min from now — AM/PM/date slip")
                    tag = "✅ PASS" if ok else "⚠️ FAIL"
                    print(f"\n### [{pid}] {label}  tool_calls={tools}  {tag}")
                    for n in notes:
                        print(f"        {n}")
                    print(f"WANT:   {ph['want']}\nREPLY:  {reply[:600]}\n" + "-" * 78)
                else:
                    gathered = annotate_seen(_gathered(ph["cal"](), ph["mail"]()), seen)
                    text = (HEARTBEAT_PROMPT
                            + "\n\n## Gathered for you (reason over this — don't re-fetch):\n"
                            + gathered)
                    directive = delivery_directive(gathered)
                    if directive:
                        text += "\n\n" + directive
                    try:
                        r = await client.post(
                            URL, headers={"Authorization": f"Bearer {secret}"},
                            json={"phone": SILO, "text": text, "internal": True,
                                  "model": BG_MODEL, "thinking_level": "MEDIUM"})
                        d = r.json()
                        reply = (d.get("reply") or "").strip()
                        tools = d.get("tool_calls", 0)
                    except Exception as e:
                        reply, tools = f"[ERROR {e}]", 0
                    quiet = _is_quiet(reply)
                    if not quiet:
                        all_replies.append(reply.lower())
                        for mid in ids_covered_by_alert(gathered, reply, bool(directive)):
                            seen[mid] = datetime.now(ET).isoformat()
                    mm = ph.get("must_mention")
                    hit = (not mm) or any(k in reply.lower() for k in mm)
                    if ph["expect"] == "silent":
                        ok = quiet
                    else:
                        ok = (not quiet) and len(reply) > 10 and hit
                    note = ""
                    if ph["expect"] == "alert" and not quiet and mm and not hit:
                        note = "  ← alerted about the WRONG thing"
                    # Pair scoring: the info must land EXACTLY ONCE across the
                    # pair. Tick 1 silent is provisionally failed; if tick 2
                    # then alerts (first surfacing), tick 2 passes and tick 1
                    # is retro-credited. Tick 2 alerting AFTER tick 1 alerted
                    # stays a genuine repeat-spam failure.
                    pair = ph.get("pair")
                    if pair:
                        st = pair_state.setdefault(pair, {"alerts": 0, "first_quiet": None})
                        if st["first_quiet"] is None:      # this is tick 1
                            st["first_quiet"] = quiet
                            st["alerts"] += (0 if quiet else 1)
                            if quiet:
                                note = "  ← silent; may surface next tick (pair-scored)"
                        else:                               # this is tick 2
                            st["alerts"] += (0 if quiet else 1)
                            if not quiet and st["first_quiet"] and hit:
                                ok = True
                                npass += 1; nfail -= 1  # retro-credit tick 1
                                note = ("  ← surfaced ONE TICK LATE but exactly once "
                                        "(tick 1 retro-credited)")
                            elif quiet and st["alerts"] == 0:
                                ok = False
                                note = "  ← NEVER surfaced across the pair (over-suppression)"
                    if not ok and quiet and ph.get("silent_ok_if_reminder"):
                        covering = await conn.fetchrow(
                            "SELECT text FROM hal_reminders WHERE phone=$1 AND "
                            "text ILIKE $2 AND created_at >= $3", SILO,
                            ph["silent_ok_if_reminder"], start)
                        if covering:
                            ok = True
                            note = (f"  ← silent BUT covered by its own reminder "
                                    f"({covering['text'][:40]!r}) — correct judgment")
                    if not ok and quiet and ph.get("ok_if_covered") and mm:
                        prior = " ".join(all_replies)
                        if any(k in prior for k in mm):
                            ok = True
                            note = "  ← silent BUT an earlier reply already covered it"
                    tag = "✅ PASS" if ok else "⚠️ FAIL"
                    print(f"\n### [{pid}] {label}  expect={ph['expect']}  "
                          f"tool_calls={tools}  {tag}{note}\n"
                          f"WANT:   {ph['want']}\n"
                          f"REPLY:  {reply[:500] if reply else '(silent — empty)'}\n" + "-" * 78)
                npass += ok
                nfail += (not ok)
    finally:
        await _restore(conn, snap)
        for t, col in CLEAN:
            await conn.execute(
                f"DELETE FROM {t} WHERE {col}=$1 AND created_at >= $2", SILO, start)
        await conn.execute(
            "UPDATE hal_user_profiles SET extra_data = extra_data - 'hb_seen' "
            "WHERE phone=$1 AND extra_data ? 'hb_seen'", SILO)
        await conn.close()
        print(f"\nrestored conversation+profile; deleted rows created since {start:%H:%M}")

    print(f"\nDAY RESULT: {npass} pass / {nfail} fail "
          f"(keyword checks are heuristics — read the replies; "
          f"silence and the DB reminder check are decisive)")


if __name__ == "__main__":
    _root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for sub in ("packages/ag-db", "packages/ag-common", "services/hal-orchestrator"):
        sys.path.insert(0, os.path.join(_root, sub))
    asyncio.run(main())
