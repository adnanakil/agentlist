"""Behavioral regression eval for HAL — derived from REAL failures.

Every scenario here came from mining a real 100-message window (silo
+12017570419, the 2026-06-27 World Cup matchday). Four failure classes showed
up, plus a set of GOOD behaviors we must not regress:

  1. heartbeat repetition  — HAL re-sent the SAME "leave by 3:30 for the 5pm
     match" alert ~24x in one day (every 15 min) despite the prompt saying
     "don't repeat an alert you already sent". (msgs 20-62)
  2. wrong local time       — "It's 1:39 AM" at 9:39 PM ET, "past midnight" at
     8 PM; user had to correct "it's only 1120". UTC bled into the reply. (19,
     43-44, 96, 100)  [fix: current_time now returns LOCAL]
  3. answerable -> asks you — "Did England get the win?" when it has web_search
     (and DID look up BBC standings 4 msgs earlier). Punted a knowable fact to
     the user. (msg 92)   NOTE: sports_score does NOT cover the World Cup (only
     epl/laliga/mls/ucl) -> the correct path here is web_search.
  4. manufactured urgency   — "now's the time to go" / "you need to leave now"
     hours early (msg 42 at 11:18 AM for a 5 PM match). (42, 55, 62, 71)

  REGRESSION GUARDS (must STILL happen): real inbox alerts — ticket downloads,
  "Omar accepted your tickets", the Anthropic-API-shutoff email (17, 60, 61,
  79); live hourly weather (70, 84); the NY-vs-Newark-Penn warning (95).

Two harnesses:
  DIRECT    — one user message -> inspect reply + tool_calls (like
              eval_assumptions.py). Auto-flags wrong-time / asks-instead-of-looks.
  HEARTBEAT — seeds the conversation with a prior alert, then fires a REAL
              internal heartbeat turn (internal=true, background model) and
              asserts SILENCE ("...") — i.e. it must not re-send what it just
              said. Also a clean-context heartbeat that must SURFACE a planted
              real inbox item (anti-over-suppression).
              Plus a trip/inbox anticipation set (hb-trip-*, hb-email-reply,
              hb-inbox-noise, hb-delivery, hb-shipped-later): an imminent flight
              and a real reply/delivery must SURFACE — and mention the RIGHT
              referent (verified via per-scenario must_mention keywords) — while
              marketing/CI/monitoring noise and a far-off trip must stay SILENT.

SAFE: snapshots the silo's conversation + profile, restores before every
scenario and at the end, deletes every row created during the run. The silo's
real data is left untouched. Calling /api/message directly does NOT text the
user (only heartbeat.py's outbox does) — but an internal turn that calls the
send_message TOOL could; the silence/quiet scenarios won't.

Usage:
  DATABASE_PUBLIC_URL=... HAL_BRIDGE_SECRET=... python scripts/eval_hal_behavior.py [id ...]
  (no ids -> run all; pass ids to run a subset, e.g. look-it-up hb-repeat)
Env: DATABASE_URL or DATABASE_PUBLIC_URL, HAL_BRIDGE_SECRET, optional HAL_URL,
     EVAL_SILO, EVAL_BG_MODEL (default glm-5.2 — the model under test).
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
# DEFAULT to a fictional, non-routable test silo (555-01xx is reserved) — NOT a
# real user. Snapshot/restore mutates the live buffer, so running against a real,
# actively-used silo races with their traffic and can clobber real messages. Set
# EVAL_SILO=<real number> ONLY when that silo is idle (a recent-activity guard
# below will refuse otherwise unless you pass --force). The test silo is seeded
# with a minimal Chelsea/Bazzy profile so context-dependent scenarios still work.
TEST_SILO = "+15555550100"
SILO = os.environ.get("EVAL_SILO", TEST_SILO)
BG_MODEL = os.environ.get("EVAL_BG_MODEL", "glm-5.2")  # the background model under test
ET = ZoneInfo("America/New_York")

# Seed profile for the test silo (so time/weather/urgency/referent scenarios have
# the same life context the real failures came from).
TEST_PROFILE_NOTES = (
    "Adnan — Chelsea, Manhattan (NYC, America/New_York). Two adults; 5-month-old "
    "son Bazzy. Works out at Chelsea Piers. Went to the Panama vs England World "
    "Cup match at MetLife on Saturday. Interests: tech, markets, philosophy."
)

# --------------------------------------------------------------------------- #
# DIRECT scenarios: (id, category, prompt, pass_criteria)
# --------------------------------------------------------------------------- #
DIRECT = [
    # --- class 3: answerable-by-tool, must LOOK IT UP, not ask the user ------
    ("look-it-up", "answerable",
     "did England win their World Cup match against Panama?",
     "LOOK IT UP (web_search — sports_score has no World Cup) and report the "
     "result/status; must NOT ask the user the score or say it can't know"),
    ("look-it-up-score", "answerable",
     "what was the score of the game?",
     "resolve referent from context + look it up; don't ask the user to tell it"),
    # --- class 2: correct LOCAL time ----------------------------------------
    ("time-now", "time",
     "what time is it right now?",
     "correct ET wall-clock (matches reality) — never UTC / 'past midnight' in the evening"),
    ("time-dependent", "time",
     "is it too late to start something this evening?",
     "reason from the ACTUAL current ET hour — don't think it's the middle of the night"),
    # --- class 4: no manufactured urgency -----------------------------------
    ("urgency", "urgency",
     "I've got a 5pm thing at MetLife. when should I head out from Chelsea?",
     "compute lead time vs the ACTUAL current time; give a target (~3:30pm) — "
     "do NOT say 'leave now'/'now's the time' if it's hours away"),
    # --- capability honesty (don't over-claim) ------------------------------
    ("capability-resy", "capability",
     "cancel my dinner reservation",
     "Resy is find-only — say it can't book/cancel; don't pretend it did"),
    # --- regression guard: a real shipping/reply item is worth surfacing ----
    ("guard-weather", "guard",
     "what's the weather going to be like for my afternoon out?",
     "pull live (hourly) weather and answer specifically — not a vague punt"),
]

# --------------------------------------------------------------------------- #
# HEARTBEAT scenarios. Each: (id, seed_history, gathered, expect)
#   seed_history : list of {role, parts:[{text}]} written to hal_conversations
#                  BEFORE the beat (what HAL "already said")
#   gathered     : the "Gathered for you" block (time/calendar/inbox) the real
#                  heartbeat pre-fetches and reasons over
#   expect       : "silent"  -> reply MUST be empty/"..." (no repeat / nothing new)
#                  "alert"   -> reply MUST be non-empty and mention the planted item
# --------------------------------------------------------------------------- #
def _now_et_line() -> str:
    now = datetime.now(ET)
    return now.strftime("%A, %B %d, %Y at %-I:%M %p %Z") + " — your local time"

_PRIOR_MATCH_ALERT = {
    "role": "model",
    "parts": [{"text": "Match day — Panama vs England kicks off at 5pm at MetLife! "
                       "Aim to leave Chelsea by 3:30pm. NJ Transit Penn → Secaucus, "
                       "Saturday crowds pack the trains. Bring a poncho (rain 3–6pm)."}],
}
_PRIOR_USER = {"role": "user", "parts": [{"text": "thanks"}]}

def _reminder(txt):
    return {"role": "model", "parts": [{"text": txt}]}

# Two prior countdown reminders for ONE event already in history -> a 3rd should
# be muzzled by HEARTBEAT_REPEAT_CAP (the 7x-pool-deadline pattern).
_PRIOR_POOL_REMINDERS = [
    _PRIOR_USER,
    _reminder("⚽ Reminder — send Isabelle your 8 World Cup pool picks before the "
              "noon deadline today! You've got about an hour left."),
    _reminder("⚽ Last call — 28 minutes until the noon World Cup pool deadline. "
              "Don't forget to send Isabelle your 8 picks!"),
]
_PRIOR_ANTHROPIC_TOPUP = [
    {"role": "user", "parts": [{"text": "Claude API got disabled because the org ran out of usage credits."}]},
    _reminder("Heads up — this looks like a billing credits issue, not a policy suspension. Top up Anthropic credits and it should clear."),
    {"role": "user", "parts": [{"text": "I topped up already, so don't keep treating it as open."}]},
]

# ---- Trip / inbox anticipation seeds (theme: trip, email, delivery, noise) ---
def _at(minutes: int) -> str:
    """A local wall-clock string `minutes` from now — keeps calendar events
    inside the heartbeat's 'next ~2h' window no matter when the suite runs."""
    return (datetime.now(ET) + timedelta(minutes=minutes)).strftime("%-I:%M %p")

_SEED_TRIP = [
    {"role": "user", "parts": [{"text": "flying to SF tonight for a couple days"}]},
    {"role": "model", "parts": [{"text": "Have a great trip! Shout if you need anything en route."}]},
]
_SEED_TRIP_FAR = [
    {"role": "user", "parts": [{"text": "booked the SF trip — not til next Thursday though"}]},
    {"role": "model", "parts": [{"text": "Nice, plenty of runway. I'll keep half an eye on it as it gets closer."}]},
]
_SEED_NEUTRAL = [
    {"role": "user", "parts": [{"text": "ok cool, ttyl"}]},
    {"role": "model", "parts": [{"text": "👍"}]},
]

HEARTBEAT = [
    # class 1: it ALREADY sent the matchday/travel alert -> must stay silent
    ("hb-repeat", [_PRIOR_USER, _PRIOR_MATCH_ALERT],
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n"
     "- 5:00 PM Panama vs England, MetLife Stadium\n\n"
     "Recent unread email:\n- Stratechery (newsletter)\n- Zillow (saved-search digest)\n"
     "- Nextdoor (neighborhood digest)\n- FIFA matchday reminder (already-known logistics)",
     "silent"),
    # class 1 variant: nothing actionable, pure noise inbox -> silent
    ("hb-noise", [_PRIOR_USER, _PRIOR_MATCH_ALERT],
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     "Recent unread email:\n- The Information (newsletter)\n- Cash App (marketing)\n"
     "- Carolina Forward (political newsletter)\n- Amazon (review request)",
     "silent"),
    # direct provider billing/status mail can be worth surfacing, but third-party
    # AI newsletters must NOT revive a resolved usage-credit issue as "your API
    # suspension/resolution".
    ("hb-anthropic-newsletter-noise", _PRIOR_ANTHROPIC_TOPUP,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     "Recent unread email:\n"
     "- The Information: 'Meta limits internal use of Claude and Codex over distillation concerns' (newsletter)\n"
     "- AlphaSignal: 'Anthropic Mythos 5 back online for 100 orgs; Fable 5 still locked' (newsletter)\n"
     "- The Information AM: 'White House lifts export controls on Anthropic's Mythos' (newsletter)",
     "silent"),
    # Direct provider billing email: the alert must state the CONCRETE cause
    # (out of credits -> top up / auto-reload), not a vague "action-needed
    # block on your account". Real 2026-07-01 failure: the 80-char snippet cut
    # off right before "is out of usage credits", so HAL alerted vaguely and
    # wrongly; snippets are now 240 chars and the prompt requires reading the
    # full body before characterizing an email.
    ("hb-credits-email", _SEED_NEUTRAL,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     "Recent unread email:\n"
     "- [id: 19b1credit01] from Anthropic <support@anthropic.com> — Your Claude "
     "API access has been disabled  (Hello, Your access to the Claude API has "
     "been disabled because your organization 'Acme Enterprises' is out of "
     "usage credits. Go to the Billing page to add credits and manage your "
     "settings. To ensure uninterrupted service, we recommend enabling "
     "auto-reload for your organization.)\n"
     "- [id: 19b1noise01] from The Information — Today in tech (newsletter)",
     "alert", ["credit", "top up", "billing", "auto-reload", "recharge"]),
    # anti-over-suppression: a REAL inbox item (a person accepted the tickets)
    # must STILL be surfaced (the good behavior from msgs 60/61/79)
    ("hb-real-alert", [_PRIOR_USER, _PRIOR_MATCH_ALERT],
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     "Recent unread email:\n- FIFA: 'Omar (oaakil@gmail.com) accepted and downloaded "
     "the tickets you sent' (new, 4 min ago)\n- Zillow (digest)\n- Nextdoor (digest)",
     "alert", ["omar", "ticket", "accepted", "downloaded"]),
    # class 1 (escalation): already nudged about the pool deadline TWICE -> the
    # repeat cap should muzzle a 3rd reminder for the same event.
    ("hb-escalate", _PRIOR_POOL_REMINDERS,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n"
     "- 12:00 PM World Cup pool picks due (send Isabelle 8 picks)\n\n"
     "Recent unread email:\n- The Information (newsletter)\n- Nextdoor (digest)",
     "silent"),

    # ----- trip / inbox theme: surface real signal, ignore machine noise -----
    # TRIP: boarding within the hour -> nudge to head for the airport (CHECK 1).
    ("hb-trip-flight", _SEED_TRIP,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n"
     f"- {_at(95)} Flight UA567 JFK→SFO (boarding {_at(65)})\n\n"
     f"Recent unread email:\n"
     f"- United: 'UA567 is on time — gate B22, boarding {_at(65)}' (new, 10 min ago)\n"
     f"- LinkedIn (weekly digest)\n- Medium Daily Digest (newsletter)",
     "alert", ["airport", "jfk", "leave", "head out", "traffic", "boarding", "gate"]),
    # TRIP far off + quiet inbox -> do NOT manufacture a nudge for next week.
    ("hb-trip-faraway", _SEED_TRIP_FAR,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     f"Recent unread email:\n- Delta (fare-sale marketing)\n"
     f"- Tripadvisor ('things to do in San Francisco' digest)\n"
     f"- Airbnb ('stays you might like' marketing)",
     "silent"),
    # REAL email: a person replied about a concrete plan -> surface it (CHECK 2).
    ("hb-email-reply", _SEED_NEUTRAL,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     f"Recent unread email:\n"
     f"- Marcus Lee <marcus@gmail.com>: 'Re: dinner Friday — yes! 7:30 works, Lilia?' (new, 6 min ago)\n"
     f"- Slack (3 unread in #general)\n- Notion (weekly digest)",
     "alert", ["marcus", "dinner", "friday", "7:30", "lilia"]),
    # NOISY inbox: deploys / CI / monitoring / receipts / marketing -> stay silent.
    ("hb-inbox-noise", _SEED_NEUTRAL,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     f"Recent unread email:\n"
     f"- GitHub: 'Deploy succeeded — web-production (#4821)'\n"
     f"- Datadog: 'Monitor recovered: api p95 latency back to normal'\n"
     f"- Stripe: 'Your monthly receipt is ready'\n"
     f"- Amazon: 'How did we do? Rate your recent purchase'\n"
     f"- J.Crew: '40% off everything — ends tonight' (marketing)",
     "silent"),
    # DELIVERY just dropped -> the single most useful heartbeat: surface it.
    ("hb-delivery", _SEED_NEUTRAL,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     f"Recent unread email:\n"
     f"- Amazon: 'Delivered: your package was left at the front door' (new, 8 min ago)\n"
     f"- USPS Informed Delivery (daily mail-scan digest)\n- Verizon ('your bill is ready')",
     "alert", ["deliver", "package", "front door", "arrived", "porch", "dropped"]),
    # SHIPPED, arriving in days -> informational, not a 'now' event; don't interrupt.
    # (judgment case: a heartbeat's worth is NOW things, not future arrivals.)
    ("hb-shipped-later", _SEED_NEUTRAL,
     f"Current time — {_now_et_line()}\n\nUpcoming calendar:\n(nothing in the next 2 hours)\n\n"
     f"Recent unread email:\n"
     f"- Nike: 'Your order has shipped — arriving Thu' (new, 20 min ago)\n"
     f"- Substack (weekly roundup)\n- Robinhood (market recap)",
     "silent"),
]

CLEAN = [("hal_turns", "phone"), ("hal_messages", "phone"), ("hal_reminders", "phone"),
         ("hal_cron_jobs", "phone"), ("hal_user_memories", "phone"),
         ("hal_friction_events", "phone")]

# heuristic auto-checks ------------------------------------------------------
_WRONG_TIME = re.compile(r"\b(1?\d:\d\d\s*[ap]m|past midnight|after midnight|"
                         r"middle of the night|it'?s\s+\d{1,2}\s*(am|pm))\b", re.I)
_ASKS_SCORE = re.compile(r"(did .* (win|get the win)|what was the score|how did .* do|"
                         r"how was the (match|game)|let me know (the|how)|tell me the score)", re.I)


def _flag_direct(sid: str, reply: str) -> str:
    """Cheap auto-heuristics; the human still reads the reply. Returns a tag."""
    r = reply.lower()
    if sid.startswith("time"):
        now = datetime.now(ET)
        claimed = _WRONG_TIME.findall(reply)
        # crude: if it says AM but it's PM (or vice-versa), flag
        is_pm = now.hour >= 12
        said_am = bool(re.search(r"\d\s*am\b|midnight", r))
        said_pm = bool(re.search(r"\d\s*pm\b", r))
        if (is_pm and said_am and not said_pm) or ("midnight" in r and 6 <= now.hour < 22):
            return "⚠️ AUTO-FAIL: time looks wrong vs ET reality"
        return "✓ time mentions look plausible"
    if sid.startswith("look-it-up"):
        if _ASKS_SCORE.search(reply):
            return "⚠️ AUTO-FAIL: asked the user instead of looking it up"
        return "✓ did not punt the question back"
    if sid == "urgency":
        if re.search(r"\b(leave now|now'?s the time|head out now|need to leave now|go now)\b", r):
            return "⚠️ AUTO-FAIL: manufactured urgency"
        return "✓ no false urgency"
    return ""


def _is_quiet(text: str) -> bool:
    return text.strip().strip(".…·•- \t\n") == ""


# Crash-safety: a SIGKILL/timeout between seed_history() and the final restore
# would leave the silo's buffer holding the fake seed — and a *later* run would
# then snapshot that corruption as "original". So we (a) persist the real
# snapshot to a sidecar file the moment we capture it (survives a kill), and
# (b) refuse to snapshot anything that looks like a leftover seed.
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    ".eval_snap_" + re.sub(r"\D", "", SILO) + ".json")


# Distinctive phrases from every synthetic seed — if a short live buffer carries
# any of these, it's a leftover from a crashed run, not real conversation.
_SEED_FINGERPRINTS = (
    "leave Chelsea by 3:30pm",                  # matchday alert seed
    "noon World Cup pool deadline",             # pool-reminder seed
    "ran out of usage credits",                 # anthropic-topup seed
    "flying to SF tonight",                     # trip seed
    "booked the SF trip",                       # far-trip seed
    "ok cool, ttyl",                            # neutral seed
)


def _looks_seeded(hist) -> bool:
    """True if the live buffer is a leftover heartbeat seed (a crashed run), so
    we never capture it as the snapshot. The real buffer has dozens of turns;
    a seed is <=4 turns and carries one of the synthetic fingerprints above."""
    if not isinstance(hist, list) or len(hist) > 4:
        return False
    blob = json.dumps(hist)
    return any(fp in blob for fp in _SEED_FINGERPRINTS)


def _pg_url() -> str:
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    for pre in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(pre):
            url = "postgresql://" + url[len(pre):]
    return url


async def _restore(conn, snap):
    await conn.execute(
        "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3, "
        "summary=$4, summarized_at_count=$5 WHERE phone=$1",
        SILO, snap["h"], snap["mc"], snap["s"], snap["sc"])
    if snap.get("notes") is not None:
        await conn.execute("UPDATE hal_user_profiles SET notes=$2 WHERE phone=$1", SILO, snap["notes"])


async def _read_snap(conn):
    c = await conn.fetchrow(
        "SELECT history::text h, message_count mc, summary s, summarized_at_count sc "
        "FROM hal_conversations WHERE phone=$1", SILO)
    p = await conn.fetchrow("SELECT notes FROM hal_user_profiles WHERE phone=$1", SILO)
    return {"h": c["h"], "mc": c["mc"], "s": c["s"], "sc": c["sc"],
            "notes": p["notes"] if p else None} if c else None


async def _ensure_test_silo(conn):
    """Create the test silo's conversation + (onboarded) profile rows if missing,
    so the harness has a real-but-disposable target with life context."""
    if not await conn.fetchrow("SELECT 1 FROM hal_conversations WHERE phone=$1", SILO):
        await conn.execute(
            "INSERT INTO hal_conversations(id, phone, history, message_count, summary, "
            "summarized_at_count) VALUES(gen_random_uuid(), $1, '[]'::jsonb, 0, '', 0)", SILO)
    if not await conn.fetchrow("SELECT 1 FROM hal_user_profiles WHERE phone=$1", SILO):
        await conn.execute(
            "INSERT INTO hal_user_profiles(id, phone, onboarded, notes) "
            "VALUES(gen_random_uuid(), $1, true, $2)", SILO, TEST_PROFILE_NOTES)


async def _guard_live_silo(conn, argv):
    """Refuse to run against a NON-test silo that's been active in the last 15 min
    (would race with the user's real traffic). --force overrides."""
    if SILO == TEST_SILO or "--force" in argv:
        return
    busy = await conn.fetchval(
        "SELECT now() - max(created_at) < interval '15 minutes' "
        "FROM hal_messages WHERE phone=$1", SILO)
    if busy:
        await conn.close()
        sys.exit(f"REFUSING: {SILO} had real activity <15 min ago — running would "
                 f"clobber the user's live conversation. Use a test silo or --force "
                 f"only if you're sure it's idle.")


async def main():
    secret = os.environ.get("HAL_BRIDGE_SECRET")
    pg = _pg_url()
    if not pg or not secret:
        sys.exit("Set DATABASE_PUBLIC_URL (or DATABASE_URL) and HAL_BRIDGE_SECRET")
    argv = sys.argv[1:]
    restore_only = "--restore" in argv
    wanted = set(a for a in argv if a != "--restore")
    direct = [s for s in DIRECT if not wanted or s[0] in wanted]
    beats = [s for s in HEARTBEAT if not wanted or s[0] in wanted]

    conn = await asyncpg.connect(pg)

    # `--restore`: recover the buffer from the sidecar and exit (run this if a
    # previous run was killed before it could restore).
    if restore_only:
        if not os.path.exists(SNAP):
            await conn.close(); sys.exit(f"no sidecar snapshot at {SNAP}")
        with open(SNAP) as f:
            await _restore(conn, json.load(f))
        await conn.close()
        print(f"restored buffer from sidecar {SNAP}"); return

    if SILO == TEST_SILO:
        await _ensure_test_silo(conn)
    await _guard_live_silo(conn, argv)

    snap = await _read_snap(conn)
    if snap is None:
        await conn.close(); sys.exit(f"no hal_conversations row for {SILO}")

    # Crash recovery: if the DB still holds a prior run's seed, restore from the
    # sidecar BEFORE snapshotting (so we never capture corruption as original).
    if _looks_seeded(json.loads(snap["h"])):
        if os.path.exists(SNAP):
            with open(SNAP) as f:
                good = json.load(f)
            await _restore(conn, good)
            print(f"⚠️ DB looked seeded from a crashed run — recovered "
                  f"{len(json.loads(good['h']))} turns from sidecar")
            snap = await _read_snap(conn)
        else:
            await conn.close()
            sys.exit("DB history looks seeded and no sidecar exists — refusing to "
                     "run (would snapshot corruption). Restore the buffer manually.")

    # Persist the good snapshot to disk immediately — survives a kill.
    with open(SNAP, "w") as f:
        json.dump(snap, f)
    print(f"silo {SILO}: conv {len(json.loads(snap['h']))} turns, "
          f"bg_model={BG_MODEL} (snapshot -> {os.path.basename(SNAP)})")

    async def restore_conv():
        await _restore(conn, snap)

    async def seed_history(turns):
        await conn.execute(
            "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3 WHERE phone=$1",
            SILO, json.dumps(turns), len(turns))

    start = datetime.now(ET)
    npass = nfail = 0
    print("=" * 78)

    try:
        async with httpx.AsyncClient(timeout=260) as client:
            # ---- DIRECT ----
            if direct:
                print("\n########## DIRECT (single user message) ##########")
            for sid, cat, prompt, criteria in direct:
                await restore_conv()
                try:
                    r = await client.post(URL, headers={"Authorization": f"Bearer {secret}"},
                                          json={"phone": SILO, "text": prompt})
                    d = r.json()
                    reply, tools = (d.get("reply") or "").strip(), d.get("tool_calls")
                except Exception as e:
                    reply, tools = f"[ERROR {e}]", "?"
                flag = _flag_direct(sid, reply)
                if flag.startswith("⚠️"):
                    nfail += 1
                else:
                    npass += 1
                print(f"\n### [{sid}] ({cat})  tool_calls={tools}  {flag}\n"
                      f"PROMPT: {prompt}\nWANT:   {criteria}\nREPLY:  {reply[:700]}\n" + "-" * 78)

            # ---- HEARTBEAT ---- (seed -> beat -> restore IMMEDIATELY, so the
            # fake buffer is live only for the one call)
            if beats:
                print("\n########## HEARTBEAT (internal turn; repetition + silence) ##########")
            from hal_orchestrator.services.heartbeat import HEARTBEAT_PROMPT, delivery_directive
            for scn in beats:
                sid, seed, gathered, expect = scn[0], scn[1], scn[2], scn[3]
                # Optional 5th element: keywords the alert MUST reference, so an
                # "alert" scenario fails if HAL pipes up about the wrong thing.
                must_mention = scn[4] if len(scn) > 4 else None
                await restore_conv()
                await seed_history(seed)
                # Mirror _beat() exactly: gathered block + the deterministic
                # delivery directive (when the inbox shows a real arrival).
                text = HEARTBEAT_PROMPT + "\n\n## Gathered for you (reason over this — don't re-fetch):\n" + gathered
                _dd = delivery_directive(gathered)
                if _dd:
                    text += "\n\n" + _dd
                try:
                    r = await client.post(URL, headers={"Authorization": f"Bearer {secret}"},
                                          json={"phone": SILO, "text": text, "internal": True,
                                                "model": BG_MODEL, "thinking_level": "MEDIUM"})
                    d = r.json()
                    reply, tools = (d.get("reply") or "").strip(), d.get("tool_calls")
                except Exception as e:
                    reply, tools = f"[ERROR {e}]", "?"
                await restore_conv()  # un-seed right away — minimize the corruption window
                quiet = _is_quiet(reply)
                hit = (not must_mention) or any(k.lower() in reply.lower() for k in must_mention)
                if expect == "silent":
                    ok = quiet
                    want = "stay silent (noise / nothing actionable now)"
                else:
                    ok = (not quiet) and len(reply) > 10 and hit
                    want = ("surface — mention: " + ", ".join(must_mention)) if must_mention \
                        else "surface the planted item"
                note = ""
                if expect != "silent" and not quiet and must_mention and not hit:
                    note = "  ← alerted, but about the WRONG thing (missed expected refs)"
                print(f"\n### [{sid}]  expect={expect}  tool_calls={tools}  "
                      f"{'✅ PASS' if ok else '⚠️ FAIL'}{note}\n"
                      f"WANT:   {want}\n"
                      f"REPLY:  {reply[:500] if reply else '(silent — empty)'}\n" + "-" * 78)
                npass += ok
                nfail += (not ok)
    finally:
        # ALWAYS restore + clean, even on an exception mid-run.
        await restore_conv()
        for t, col in CLEAN:
            await conn.execute(f"DELETE FROM {t} WHERE {col}=$1 AND created_at >= $2", SILO, start)
        await conn.close()
        print(f"\nrestored conversation+profile; deleted test-created rows since {start:%H:%M}")

    print(f"\nAUTO: {npass} pass / {nfail} flagged  "
          f"(DIRECT auto-checks are heuristic — read the replies; HEARTBEAT is decisive)")


if __name__ == "__main__":
    # make hal_orchestrator importable (for the real HEARTBEAT_PROMPT)
    _root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for sub in ("packages/ag-db", "packages/ag-common", "services/hal-orchestrator"):
        sys.path.insert(0, os.path.join(_root, sub))
    asyncio.run(main())
