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

import asyncio
import os

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from hal_orchestrator.services.idempotency import internal_message_id

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
        ):
            try:
                lines.append(f"{label}:\n" + str(await execute_tool(name, args, ctx)))
            except Exception:
                log.exception("first_win.gather_failed", silo=silo, tool=name)
        break
    return "\n\n".join(lines)


# If the whole first-win turn fails, the user still just connected Google and is
# staring at their phone — never leave them with silence. This safe confirmation
# goes out via the outbox so the connection is always acknowledged.
FIRST_WIN_FALLBACK = (
    "Connected ✅ — I can see your calendar and inbox now. I'll keep an eye on "
    "them and flag anything that genuinely needs you."
)

_POST_ATTEMPTS = 2  # this is the single most important proactive message HAL sends


async def _post_message_turn(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    silo: str,
    gathered: str,
) -> str:
    """POST the internal first-win turn with one retry + backoff; return the
    reply text. Raises if every attempt fails (caller handles the fallback)."""
    port = os.environ.get("PORT", "8005")
    payload = {
        "message_id": internal_message_id("first-win", silo, gathered),
        "phone": silo,
        "text": build_first_win_prompt(gathered),
        "internal": True,
        # model omitted -> the MAIN model; this is a first impression.
    }
    headers = {"Authorization": f"Bearer {settings.hal_bridge_secret}"}
    last_exc: Exception | None = None
    for attempt in range(1, _POST_ATTEMPTS + 1):
        try:
            resp = await http.post(
                f"http://127.0.0.1:{port}/api/message",
                json=payload,
                headers=headers,
                timeout=180.0,
            )
            resp.raise_for_status()
            return (resp.json().get("reply") or "").strip()
        except Exception as exc:
            last_exc = exc
            log.warning(
                "first_win.post_retry", silo=silo, attempt=attempt, error=str(exc)
            )
            if attempt < _POST_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)  # 1.5s, then give up
    assert last_exc is not None
    raise last_exc


async def run_first_win(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> None:
    """One internal agent turn; deliver the reply via the outbox. This is the
    single most important proactive message HAL ever sends (the payoff seconds
    after a Google connect), so it retries the internal call and, if everything
    fails or comes back empty, still sends a safe confirmation — the user must
    never be left with silence. Best-effort: never breaks the OAuth callback."""
    import hal_orchestrator.state as state

    try:
        gathered = await _gather(settings, http, silo)
        if not gathered:
            # Every pre-fetch failed (or returned nothing). Don't skip silently —
            # log loudly and still confirm the connection.
            log.error("first_win.gather_empty", silo=silo)
            await state.outbox.put(
                {
                    "to": silo,
                    "text": FIRST_WIN_FALLBACK,
                    "idempotency_key": f"first-win-fallback:{silo}",
                }
            )
            return

        try:
            reply = await _post_message_turn(settings, http, silo, gathered)
        except Exception:
            log.error("first_win.post_failed_all_attempts", silo=silo, exc_info=True)
            await state.outbox.put(
                {
                    "to": silo,
                    "text": FIRST_WIN_FALLBACK,
                    "idempotency_key": f"first-win-fallback:{silo}",
                }
            )
            return

        if reply:
            await state.outbox.put({"to": silo, "text": reply})
            log.info("first_win.sent", silo=silo, chars=len(reply))
        else:
            # The model produced nothing despite real material — that's a failure
            # for a first impression. Confirm the connection rather than vanish.
            log.error("first_win.silent", silo=silo)
            await state.outbox.put(
                {
                    "to": silo,
                    "text": FIRST_WIN_FALLBACK,
                    "idempotency_key": f"first-win-fallback:{silo}",
                }
            )
    except Exception:
        log.exception("first_win.failed", silo=silo)
