"""First win — the moment a user connects Google, prove it was worth it.

Onboarding COLLECTS well (name → tz → home → work → Google) but never
DEMONSTRATES value. The strongest moment to do that is seconds after the OAuth
callback: HAL has just gained calendar+inbox sight and the user is back in
iMessage waiting. One internal agent turn (on the MAIN model — first
impressions are not a place to save tokens) scans both and sends a single
concrete message: "Connected — you've got X tomorrow at 9, and Sarah's email
about Y looks like it needs a reply."

Fires only on a FIRST-ever connect (profile.google_connected was false when
the callback landed), so scope-upgrade reconnects don't re-trigger it.
"""

from __future__ import annotations

import os

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session

log = structlog.get_logger()

FIRST_WIN_PROMPT = """\
[FIRST WIN — the user connected their Google account to you SECONDS ago, \
during onboarding. They're back in iMessage waiting. This is your one chance \
to show the connection was worth it. They did NOT text you; they only see the \
message you send.]

I've already pulled their upcoming calendar and recent unread email for you \
(see "Gathered for you" below). Send ONE short message that:
- Confirms you're in, in a few light words ("Connected ✅" or similar).
- Surfaces the 1–2 MOST useful concrete things you can now see: their next \
real commitment ("you've got X tomorrow at 9"), and/or an email that \
genuinely needs their attention (a real person waiting on a reply, a bill or \
renewal, a delivery/confirmation they'd want to know about). Pick what a \
great human assistant would flag first — NOT a list of everything.
- Optionally ONE short line on what you'll now do quietly on your own (warn \
before meetings when traffic's bad, flag deliveries and real replies) — pick \
the one that fits what you actually saw.

Rules: 2–5 short plain-text lines, no markdown, no bullet-dump of the whole \
calendar, no questions. NEVER surface machine noise — newsletters, marketing, \
deploys/CI, receipts, digests. Use their local time for any times. If the \
calendar and inbox are genuinely empty or noise-only, send a short warm \
confirmation that you're connected and quietly keeping an eye out — say \
there's nothing needing their attention right now, and NEVER invent items."""


def build_first_win_prompt(gathered: str) -> str:
    """Prompt + pre-gathered context. Pure so evals/tests reuse the exact
    production wording."""
    return (
        FIRST_WIN_PROMPT
        + "\n\n## Gathered for you (reason over this — don't re-fetch):\n"
        + gathered
    )


async def _gather(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> str:
    """Pre-fetch time + calendar + recent unread mail (same pattern as the
    heartbeat: hand the model real material rather than hoping it fetches)."""
    from hal_orchestrator.tools.registry import ToolContext, execute_tool

    lines: list[str] = []
    async for session in db_session.get_session():
        ctx = ToolContext(phone=silo, session=session, settings=settings, http_client=http)
        for label, name, args in (
            ("Current time", "current_time", {}),
            ("Upcoming calendar", "google_calendar", {"action": "list_events"}),
            (
                "Recent unread email",
                "google_gmail",
                {"action": "list_emails", "query": "is:unread newer_than:3d", "max_results": 10},
            ),
        ):
            try:
                lines.append(f"{label}:\n" + str(await execute_tool(name, args, ctx)))
            except Exception:
                log.exception("first_win.gather_failed", silo=silo, tool=name)
        break
    return "\n\n".join(lines)


async def run_first_win(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> None:
    """One internal agent turn; deliver the reply (if any) via the outbox.
    Best-effort: a failure here must never break the OAuth callback."""
    import hal_orchestrator.state as state

    try:
        gathered = await _gather(settings, http, silo)
        if not gathered:
            return
        port = os.environ.get("PORT", "8005")
        resp = await http.post(
            f"http://127.0.0.1:{port}/api/message",
            json={
                "phone": silo,
                "text": build_first_win_prompt(gathered),
                "internal": True,
                # model omitted -> the MAIN model; this is a first impression.
            },
            headers={"Authorization": f"Bearer {settings.hal_bridge_secret}"},
            timeout=180.0,
        )
        resp.raise_for_status()
        reply = (resp.json().get("reply") or "").strip()
        if reply:
            await state.outbox.put({"to": silo, "text": reply})
            log.info("first_win.sent", silo=silo, chars=len(reply))
        else:
            log.warning("first_win.silent", silo=silo)
    except Exception:
        log.exception("first_win.failed", silo=silo)
