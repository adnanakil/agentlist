"""DRY-RUN of the post-event follow-up sweep against one production silo.

STRICTLY READ-ONLY: reads archive/summary/profile from prod Postgres and calls
the model; never writes rows, never touches the outbox, never posts to
/api/message. Prints the scanner's events and, for each, what the checkin and
suggest drafts WOULD say (with a real read-only tool loop so `places` /
`web_search` suggestions are genuine).

Usage: python3 dryrun_followup.py <silo>
Env: full hal-orchestrator Railway env exported, DATABASE_URL overridden to
the public asyncpg URL.
"""

import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.join(ROOT, "services", "hal-orchestrator"))

import httpx  # noqa: E402

SILO = sys.argv[1] if len(sys.argv) > 1 else "chat957723300680920907"
GROUP_NAME = os.environ.get("DRYRUN_GROUP_NAME", "group chat")

def _is_group(s):
    return s.startswith("chat")

IS_GROUP = _is_group(SILO)

# Read-only tools the draft turn may really execute; everything else is
# stubbed so a dry-run can never mutate state or text anyone.
SAFE_TOOLS = {
    "places", "web_search", "web_fetch", "current_time", "get_weather",
    "travel_time", "sports_score",
}
MAX_ITERS = 8


async def run_draft(http, settings, session, sysp, hist, prompt):
    from hal_orchestrator.prompts.tool_defs import MAIN_TOOLS
    from hal_orchestrator.services.gemini import call_gemini
    from hal_orchestrator.tools.registry import ToolContext, execute_tool

    ctx = ToolContext(
        phone=SILO, session=session, settings=settings, http_client=http,
        chat_id=SILO if IS_GROUP else None, is_group=IS_GROUP,
    )
    history = hist + [{"role": "user", "parts": [{"text": prompt}]}]
    tool_calls = []
    for _ in range(MAX_ITERS):
        resp = await call_gemini(
            http, settings, history, tools=MAIN_TOOLS, system=sysp,
            model=settings.gemini_background_model, thinking_level="MEDIUM",
        )
        if not resp:
            return "(model call failed)", tool_calls
        parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        calls = [p for p in parts if "functionCall" in p]
        if not calls:
            text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
            return text or "(empty)", tool_calls
        history.append({"role": "model", "parts": parts})
        responses = []
        for fc in calls:
            name = fc["functionCall"]["name"]
            args = fc["functionCall"].get("args", {})
            tool_calls.append(name)
            if name in SAFE_TOOLS:
                result = await execute_tool(name, args, ctx)
            else:
                result = f"(dry-run: tool '{name}' disabled)"
            responses.append({
                "functionResponse": {"name": name, "response": {"content": str(result)}}
            })
        history.append({"role": "user", "parts": responses})
    return "(hit iteration cap)", tool_calls


async def main():
    from ag_common.config import HalOrchestratorConfig
    from ag_db.session import create_engine_and_session, get_session

    settings = HalOrchestratorConfig()
    engine, _ = create_engine_and_session(settings.database_url)
    import ag_db.session as dbs
    import hal_orchestrator.state as state

    state.settings = settings

    # Counterfactual mode: DRYRUN_CUTOFF=<ISO> hides all archive messages
    # after that instant, simulating "what would the sweep have seen/said at
    # that point in time".
    cutoff = os.environ.get("DRYRUN_CUTOFF")
    if cutoff:
        import hal_orchestrator.services.followup as fu

        _orig_load = fu.load_recent_archive

        async def _cut_load(session, silo, limit=fu.SCAN_MESSAGES):
            msgs = await _orig_load(session, silo, limit)
            return [m for m in msgs if m["at"] <= cutoff]

        fu.load_recent_archive = _cut_load
        print(f"(counterfactual: archive cut at {cutoff})")

    # DRYRUN_NOW=<ISO with tz>: fake the "current time" block the draft model
    # sees, so a counterfactual reads as if run at that moment.
    fake_now = os.environ.get("DRYRUN_NOW")
    if fake_now:
        from datetime import datetime as _dt

        import hal_orchestrator.prompts.system as sysmod

        _fixed = _dt.fromisoformat(fake_now)

        def _fixed_now_block(tz=sysmod.USER_TZ):
            local = _fixed.astimezone(tz)
            return (
                "## Current time\n"
                f"{local:%A, %B %-d, %Y at %-I:%M %p %Z}"
            )

        sysmod._now_block = _fixed_now_block
        print(f"(counterfactual: clock fixed at {fake_now})")

    from hal_orchestrator.prompts.system import (
        SYSTEM_PROMPT,
        USER_TZ,
        build_user_context,
    )
    from hal_orchestrator.services.conversation import get_summary, validate_history
    from hal_orchestrator.services.followup import (
        build_checkin_prompt,
        build_suggest_prompt,
        load_recent_archive,
        pick_phase,
        scan_silo_events,
    )
    from hal_orchestrator.services.profiles import get_profile
    from datetime import datetime, timezone

    async with httpx.AsyncClient(timeout=180) as http:
        async with dbs._session_factory() as session:
            summary = await get_summary(session, SILO)
            print(f"=== SCAN of {SILO} ===")
            events = await scan_silo_events(settings, http, session, SILO, summary)
            if not events:
                print("scanner found no HAL-planned past events — raw debug:")
                import json as _json
                from datetime import datetime as _dt, timezone as _tz

                from hal_orchestrator.services.followup import SCAN_SYSTEM
                from hal_orchestrator.services.gemini import call_gemini

                msgs_dbg = await load_recent_archive(session, SILO)
                print(f"  archive messages in window: {len(msgs_dbg)}")
                if msgs_dbg:
                    print(f"  first: {msgs_dbg[0]['at']}  last: {msgs_dbg[-1]['at']}")
                payload = {
                    "now": _dt.now(_tz.utc).isoformat(timespec="minutes"),
                    "chat_summary": (summary or "")[:1200],
                    "messages": msgs_dbg,
                }
                resp = await call_gemini(
                    http, settings,
                    [{"role": "user", "parts": [{"text": _json.dumps(payload, indent=1)}]}],
                    system=SCAN_SYSTEM, model=settings.gemini_background_model,
                )
                if not resp:
                    print("  call_gemini returned None (model/provider failure)")
                else:
                    parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                    print("  RAW REPLY:")
                    print("  " + "\n  ".join(
                        "".join(p.get("text", "") for p in parts if "text" in p).splitlines()
                    ))
            now = datetime.now(timezone.utc)
            for ev in events:
                phase_now = pick_phase(ev["ended_at"], now, False, False)
                print(f"\nEVENT: {ev['summary']}")
                print(f"  ended_at (scanner estimate): {ev['ended_at']}")
                print(f"  followed_up already: {ev['followed_up']}")
                print(f"  phase due RIGHT NOW: {phase_now}")

            profile = await get_profile(session, SILO)
            sysp = SYSTEM_PROMPT + build_user_context(
                silo=SILO, profile=profile, is_group=IS_GROUP,
                group_name=GROUP_NAME if IS_GROUP else None,
                ambient_watch=False,
            )
            if summary:
                sysp += (
                    "\n\n## Conversation summary so far (older context)\n" + summary
                )
            msgs = await load_recent_archive(session, SILO, limit=40)
            hist = validate_history([
                {
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": f"[{m['at']}] {m['text']}"}],
                }
                for m in msgs
            ])

            for ev in events:
                when_local = (
                    f"{ev['ended_at'].astimezone(USER_TZ):%A %b %-d, %-I:%M %p}"
                )
                for phase, builder in (
                    ("checkin", build_checkin_prompt),
                    ("suggest", build_suggest_prompt),
                ):
                    print(f"\n=== DRAFT [{phase}] for: {ev['summary'][:70]} ===")
                    text, tools = await run_draft(
                        http, settings, session, sysp, hist,
                        builder(ev["summary"], when_local),
                    )
                    if tools:
                        print(f"  (tools used: {', '.join(tools)})")
                    print(text)
    await engine.dispose()


asyncio.run(main())
