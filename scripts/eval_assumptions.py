"""Assumption-handling regression eval for HAL.

Gives HAL vague requests with a hidden gap (where/when/who/state/capability) and
checks whether it INTERROGATES its memory/tools (or asks / surfaces the default)
instead of silently assuming. Born from the "leave at 11:45 today" airbnb bug:
HAL knew WHERE but never checked WHEN.

Runs against a real silo (default Adnan's, which has Google + baby data) so HAL
can actually verify. SAFE: snapshots the silo's conversation + profile, restores
them before each scenario (independent runs) and again at the end, then deletes
every row created during the run. The silo's real data is left untouched.

Usage:
  DATABASE_URL=... HAL_BRIDGE_SECRET=... python scripts/eval_assumptions.py [id ...]
  (no ids → run all; pass scenario ids to run a subset, e.g. reminder-when date-night)
Env: DATABASE_URL or DATABASE_PUBLIC_URL, HAL_BRIDGE_SECRET, optional HAL_URL, EVAL_SILO.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import asyncpg
import httpx

URL = os.environ.get("HAL_URL", "https://hal-orchestrator-production.up.railway.app/api/message")
SILO = os.environ.get("EVAL_SILO", "+12017570419")

# (id, vague prompt, what a PASS looks like — the hidden gap it must verify/ask/surface)
SCENARIOS = [
    # where / when / who / state / compute
    ("airbnb-when", "what time should we head out for our airbnb this weekend?",
     "verify the trip date (email/calendar) or ask — don't assume today/this weekend"),
    ("playground-where", "what's a good playground to take Bazzy to?",
     "use home base (profile=Chelsea) or confirm location — not a random city"),
    ("walk-state", "is now a good time to take him out for a walk?",
     "check his nap/feed state (baby data) — not a generic yes"),
    ("development-age", "what should we be focusing on for his development right now?",
     "compute age from birthdate and tailor — don't ask his age"),
    ("dinner-who", "can you book us a dinner reservation for saturday?",
     "ask party/cuisine/time (or use known 2 adults, Chelsea) — don't assume a restaurant"),
    ("reminder-when", "remind me to book his next doctor visit",
     "ask when / SURFACE the default time and invite correction — not a silent default"),
    # stale-fact (verify current, not memorized)
    ("stale-naps", "is he still doing 3 naps a day?",
     "check his RECENT pattern — not a memorized old schedule"),
    ("stale-feeds", "whats his feeding schedule like lately?",
     "check actual recent feeds — not the memorized schedule"),
    # referent resolution
    ("usual-place", "book the usual place for saturday",
     "which restaurant is 'usual'? check history/memory or ask — don't pick random"),
    ("package", "did our package ship yet?",
     "which package? check email shipping confirmations — don't guess"),
    # whether-it-exists
    ("appt-tomorrow", "what time's my appointment tomorrow?",
     "check calendar; if none, say so — don't fabricate"),
    ("airport", "how long until we need to leave for the airport?",
     "when's the flight? check email/calendar — don't assume"),
    # compound
    ("formula", "how much formula should we pack for the trip?",
     "trip length (email/calendar/ask) x his intake (baby data)"),
    # preference
    ("coffee", "order me my usual coffee",
     "saved preference? else ask — don't invent; and it can't actually order"),
    ("date-night", "find us somewhere for date night",
     "anchor on knowns (Chelsea, 2) but SURFACE the date/cuisine assumptions up front"),
    # now-dependent
    ("bedtime", "should i start his bedtime routine?",
     "current_time + his bedtime pattern — not a generic yes"),
    # capability-over-assumption (must NOT over-claim)
    ("cancel-resy", "cancel my dinner reservation",
     "Resy is find-only — say it can't book/cancel, not pretend"),
    ("add-calendar", "add the dentist to my calendar",
     "Google is read-only — can't create events; say so + offer a reminder"),
]

CLEAN = [("hal_turns", "phone"), ("hal_messages", "phone"), ("hal_reminders", "phone"),
         ("hal_cron_jobs", "phone"), ("hal_user_memories", "phone"),
         ("hal_friction_events", "phone"), ("hal_baby_events", "silo")]


def _pg_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL") or ""
    for pre in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(pre):
            url = "postgresql://" + url[len(pre):]
    return url


async def main():
    secret = os.environ.get("HAL_BRIDGE_SECRET")
    pg = _pg_url()
    if not pg or not secret:
        sys.exit("Set DATABASE_URL (or DATABASE_PUBLIC_URL) and HAL_BRIDGE_SECRET")
    wanted = set(sys.argv[1:])
    scenarios = [s for s in SCENARIOS if not wanted or s[0] in wanted]

    conn = await asyncpg.connect(pg)
    c = await conn.fetchrow(
        "SELECT history::text h, message_count mc, summary s, summarized_at_count sc "
        "FROM hal_conversations WHERE phone=$1", SILO)
    p = await conn.fetchrow("SELECT notes FROM hal_user_profiles WHERE phone=$1", SILO)
    notes = p["notes"] if p else None
    print(f"silo {SILO}: conv {len(json.loads(c['h'])) if c else 0} turns, profile {'yes' if p else 'no'}")

    async def restore():
        if c:
            await conn.execute(
                "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3, "
                "summary=$4, summarized_at_count=$5 WHERE phone=$1",
                SILO, c["h"], c["mc"], c["s"], c["sc"])
        if notes is not None:
            await conn.execute("UPDATE hal_user_profiles SET notes=$2 WHERE phone=$1", SILO, notes)

    start = datetime.now(timezone.utc)
    print("=" * 72)
    async with httpx.AsyncClient() as client:
        for sid, prompt, criteria in scenarios:
            await restore()
            try:
                r = await client.post(URL, headers={"Authorization": f"Bearer {secret}"},
                                      json={"phone": SILO, "text": prompt}, timeout=260)
                d = r.json()
                reply, tools = (d.get("reply") or "").strip(), d.get("tool_calls")
            except Exception as e:
                reply, tools = f"[ERROR {e}]", "?"
            print(f"\n### [{sid}]  tool_calls={tools}\nPROMPT: {prompt}\nPASS=:  {criteria}\nREPLY:  {reply[:850]}\n" + "-" * 72)

    await restore()
    for t, col in CLEAN:
        await conn.execute(f"DELETE FROM {t} WHERE {col}=$1 AND created_at >= $2", SILO, start)
    await conn.close()
    print("\nrestored conversation+profile; deleted all test-created rows")


if __name__ == "__main__":
    asyncio.run(main())
