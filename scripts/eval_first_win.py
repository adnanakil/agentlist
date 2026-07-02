"""First-win eval — does HAL's post-Google-connect message actually land?

Feeds the EXACT production first-win prompt (services/first_win.py) synthetic
calendar+inbox personas through the real pipeline (internal turn, MAIN model)
and grades the one message a brand-new user would receive seconds after
connecting Google. The bar: concrete and specific (their real next commitment
/ an email that matters), no noise, no fabrication when there's nothing, no
laundry list.

Same safety discipline as the other evals: test silo, snapshot/restore,
delete created rows. Usage:
  DATABASE_PUBLIC_URL=... HAL_BRIDGE_SECRET=... python scripts/eval_first_win.py [id ...]
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
ET = ZoneInfo("America/New_York")


def _at(minutes: int) -> str:
    return (datetime.now(ET) + timedelta(minutes=minutes)).strftime("%a %-I:%M %p")


def _now_line() -> str:
    return datetime.now(ET).strftime("%A, %B %d, %Y at %-I:%M %p %Z") + " — your local time"


def _gathered(cal: str, mail: str) -> str:
    return (f"Current time:\n{_now_line()}\n\n"
            f"Upcoming calendar:\n{cal}\n\n"
            f"Recent unread email:\n{mail}")


# (id, calendar, inbox, must_mention_any, must_not_mention, description)
PERSONAS = [
    ("busy-exec",
     f"- {_at(60 * 14)} Board prep w/ Jenna — office\n"
     f"- {_at(60 * 38)} Dentist — Dr. Liu",
     "- [id: fw1aa] from Marcus Lee <marcus@vantagelp.com> — Re: MSA redlines  "
     "(Adnan — can you turn the redlines by Friday? Legal wants a clean copy before the board sees it)\n"
     "- [id: fw1bb] from Delta — Your trip confirmation: JFK ✈ SFO  (Confirmation #ABC123, departs next Tue)\n"
     "- [id: fw1cc] from Stratechery — Today's update (newsletter)\n"
     "- [id: fw1dd] from GitHub — Deploy succeeded (#4931)\n"
     "- [id: fw1ee] from J.Crew — 40% off everything (marketing)",
     ["board", "jenna", "marcus", "redlines", "msa", "friday"],
     ["stratechery", "j.crew", "github", "deploy", "40%"],
     "flag the board prep and/or Marcus's Friday deadline; ignore all noise"),

    ("new-parent",
     f"- {_at(60 * 20)} Bazzy pediatrician checkup — Dr. Morales",
     "- [id: fw2aa] from Amazon — Delivered: your package was left at the front door  "
     "(Your bottle warmer has been delivered. See the delivery photo)\n"
     "- [id: fw2bb] from Jess <jess@gmail.com> — Re: weekend at your mom's  "
     "(should I book the Friday flights or are we driving?)\n"
     "- [id: fw2cc] from USPS Informed Delivery — daily digest\n"
     "- [id: fw2dd] from Nextdoor — Trending near you (digest)",
     ["pediatrician", "morales", "delivered", "bottle", "jess", "weekend", "flight"],
     ["usps", "nextdoor", "digest"],
     "flag the checkup, the delivered bottle warmer and/or Jess's question"),

    ("empty-quiet",
     "(no upcoming events in the next 7 days)",
     "- [id: fw3aa] from Medium Daily Digest — Stories for you (newsletter)\n"
     "- [id: fw3bb] from Spotify — Your weekly mix is ready (marketing)",
     ["connect", "eye", "watch", "set", "quiet", "nothing"],
     # Fabrication = asserting a CURRENT item that doesn't exist ("you've got X
     # tomorrow"), not merely using words like "meeting" in a forward-looking
     # promise ("I'll warn you before meetings").
     ["you've got", "tomorrow at", "was delivered", "your flight", "departs",
      "medium", "spotify"],
     "graceful: confirm connected + quietly watching; invent NOTHING"),
]

CLEAN = [("hal_turns", "phone"), ("hal_messages", "phone"), ("hal_reminders", "phone"),
         ("hal_cron_jobs", "phone"), ("hal_user_memories", "phone"),
         ("hal_friction_events", "phone")]
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    ".eval_snap_" + re.sub(r"\D", "", SILO) + ".json")


def _pg_url() -> str:
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    for pre in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(pre):
            url = "postgresql://" + url[len(pre):]
    return url


async def main():
    # sys.path bootstrap happens in __main__ so this import gets the REAL prompt
    from hal_orchestrator.services.first_win import build_first_win_prompt

    secret = os.environ.get("HAL_BRIDGE_SECRET")
    pg = _pg_url()
    if not pg or not secret:
        sys.exit("Set DATABASE_PUBLIC_URL (or DATABASE_URL) and HAL_BRIDGE_SECRET")
    wanted = {a for a in sys.argv[1:] if not a.startswith("--")}
    personas = [p for p in PERSONAS if not wanted or p[0] in wanted]

    conn = await asyncpg.connect(pg)
    snap = await conn.fetchrow(
        "SELECT history::text h, message_count mc FROM hal_conversations WHERE phone=$1", SILO)
    if snap is None:
        await conn.close(); sys.exit(f"no hal_conversations row for {SILO} — run eval_hal_behavior once first")

    start = datetime.now(ET)
    npass = nfail = 0
    print(f"first-win personas on {SILO} (MAIN model, real pipeline)")
    print("=" * 78)
    try:
        async with httpx.AsyncClient(timeout=260) as client:
            for pid, cal, mail, must_any, must_not, desc in personas:
                # fresh, minimal onboarding-ish history for each persona
                await conn.execute(
                    "UPDATE hal_conversations SET history=$2::jsonb, message_count=2 WHERE phone=$1",
                    SILO, json.dumps([
                        {"role": "user", "parts": [{"text": "ok connecting google now"}]},
                        {"role": "model", "parts": [{"text": "Tap the link and I'll take it from there 🔗"}]},
                    ]))
                try:
                    r = await client.post(URL, headers={"Authorization": f"Bearer {secret}"},
                                          json={"phone": SILO, "internal": True,
                                                "text": build_first_win_prompt(_gathered(cal, mail))})
                    d = r.json()
                    reply, tools = (d.get("reply") or "").strip(), d.get("tool_calls")
                except Exception as e:
                    reply, tools = f"[ERROR {e}]", "?"
                rl = reply.lower()
                hits = [k for k in must_any if k in rl]
                leaks = [k for k in must_not if k in rl]
                ok = bool(reply) and bool(hits) and not leaks and len(reply) <= 900
                notes = []
                if not reply:
                    notes.append("EMPTY — first win never arrived")
                if not hits:
                    notes.append(f"missed all of: {', '.join(must_any)}")
                if leaks:
                    notes.append(f"surfaced noise/fabrication: {', '.join(leaks)}")
                if len(reply) > 900:
                    notes.append(f"too long ({len(reply)} chars) — laundry list?")
                print(f"\n### [{pid}]  tool_calls={tools}  {'✅ PASS' if ok else '⚠️ FAIL'}"
                      f"{('  ' + '; '.join(notes)) if notes else ''}")
                print(f"WANT:   {desc}\nREPLY:  {reply[:700]}\n" + "-" * 78)
                npass += ok
                nfail += (not ok)
    finally:
        await conn.execute(
            "UPDATE hal_conversations SET history=$2::jsonb, message_count=$3 WHERE phone=$1",
            SILO, snap["h"], snap["mc"])
        for t, col in CLEAN:
            await conn.execute(f"DELETE FROM {t} WHERE {col}=$1 AND created_at >= $2", SILO, start)
        await conn.close()
        print(f"\nrestored conversation; deleted rows created since {start:%H:%M}")

    print(f"\nFIRST-WIN RESULT: {npass} pass / {nfail} fail")


if __name__ == "__main__":
    _root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for sub in ("packages/ag-db", "packages/ag-common", "services/hal-orchestrator"):
        sys.path.insert(0, os.path.join(_root, sub))
    asyncio.run(main())
