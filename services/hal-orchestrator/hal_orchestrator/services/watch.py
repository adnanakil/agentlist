"""Notify-when-condition watches (WATCH_FEATURE_SPEC.md).

A watch is persistent state (a HalWatch row) + ONE shared background checker —
not a long-lived task. Each poll spins up a cheap, shallow, throwaway Gemini
call (flash-lite + MINIMAL thinking + a 3-tool allow-list) that does ONE check
and returns a structured verdict. This survives redeploys, is enumerable/
cancellable, and is cost-bounded.

A watch is SILENT on every outcome except a real hit, and terminates on the
first of: condition_met (notify → deactivate), terminal (situation resolved,
e.g. game FINAL), expiry, max_polls, 3 consecutive failed polls, or user cancel.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalWatch
from ag_db.session import get_session

log = structlog.get_logger()

POLL_DEPTH_CAP = 3          # tool-call rounds within a single poll
MIN_POLL_SECONDS = 90
BREAKER_FAILS = 3
WATCH_POLL_TOOLS = ["sports_score", "web_search", "web_fetch"]


# --------------------------------------------------------------------------- #
# CRUD (mirrors services/cron.py)
# --------------------------------------------------------------------------- #


async def create_watch(
    session: AsyncSession,
    phone: str,
    condition: str,
    check_prompt: str,
    notify: str,
    expires_at: datetime,
    poll_every_seconds: int = 150,
    max_polls: int = 60,
    is_group: bool = False,
    chat_id: str | None = None,
    sender_phone: str | None = None,
) -> tuple[HalWatch | None, str | None]:
    """Create a watch. Returns (watch, None) or (None, error)."""
    poll_every_seconds = max(MIN_POLL_SECONDS, int(poll_every_seconds))

    active = await list_watch(session, phone)
    # Per-silo active cap.
    settings = _settings()
    if len(active) >= settings.watch_max_per_silo:
        return None, (
            f"You're already watching {len(active)} things here (max "
            f"{settings.watch_max_per_silo}). Cancel one first."
        )
    # Same-condition dedupe.
    cond_norm = condition.strip().lower()
    if any(w.condition.strip().lower() == cond_norm for w in active):
        return None, "I'm already watching that exact thing — I'll let you know."

    watch = HalWatch(
        phone=phone,
        condition=condition,
        check_prompt=check_prompt,
        notify=notify,
        expires_at=expires_at,
        poll_every_seconds=poll_every_seconds,
        max_polls=max(1, int(max_polls)),
        next_run_at=datetime.now(timezone.utc) + timedelta(seconds=poll_every_seconds),
        is_group=is_group,
        chat_id=chat_id,
        sender_phone=sender_phone,
    )
    session.add(watch)
    await session.flush()
    log.info("watch.created", phone=phone, condition=condition[:60], expires_at=str(expires_at))
    return watch, None


async def list_watch(session: AsyncSession, phone: str) -> list[HalWatch]:
    stmt = (
        select(HalWatch)
        .where(HalWatch.phone == phone, HalWatch.active == True)  # noqa: E712
        .order_by(HalWatch.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_watch(session: AsyncSession, watch_id: str, phone: str) -> bool:
    try:
        uid = UUID(watch_id)
    except ValueError:
        return False
    stmt = select(HalWatch).where(HalWatch.id == uid, HalWatch.phone == phone)
    watch = (await session.execute(stmt)).scalar_one_or_none()
    if watch is None:
        return False
    await session.delete(watch)
    await session.flush()
    return True


async def cancel_all(session: AsyncSession, phone: str) -> int:
    watches = await list_watch(session, phone)
    for w in watches:
        await session.delete(w)
    await session.flush()
    return len(watches)


def _settings() -> HalOrchestratorConfig:
    import hal_orchestrator.state as state

    return state.settings


# --------------------------------------------------------------------------- #
# Poll — one cheap shallow check → structured verdict
# --------------------------------------------------------------------------- #

WATCH_POLL_SYSTEM = """You are HAL's watch-poll worker. Run ONE quick check, then stop.
- For sports/score conditions call sports_score ONCE; do NOT web_search for scores.
- Otherwise use web_search/web_fetch at most twice. You CANNOT message anyone.
- Reply with ONLY a JSON object: {"condition_met": bool, "terminal": bool, "observation": "<one line>"}
- condition_met: true only if clearly true right now. terminal: true if permanently resolved (e.g. game FINAL).
- If unsure, condition_met=false."""


def _extract_json(text: str) -> dict | None:
    """Strip markdown fences, take first { … last }, parse. None on failure."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if m:
        t = m.group(1)
    else:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            return None
        t = t[start : end + 1]
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def _poll(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    w: HalWatch,
) -> dict | None:
    """Run one shallow check. Returns the verdict dict or None on failure."""
    from hal_orchestrator.prompts.tool_defs import get_agent_tools
    from hal_orchestrator.services.gemini import call_gemini
    from hal_orchestrator.tools.registry import ToolContext, execute_tool

    tools = get_agent_tools(WATCH_POLL_TOOLS)
    ctx = ToolContext(
        phone=w.phone,
        session=session,
        settings=settings,
        http_client=http,
        chat_id=w.chat_id,
        sender_phone=w.sender_phone,
        is_group=w.is_group,
    )
    history: list[dict] = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"Condition: {w.condition}\n"
                        f"Check: {w.check_prompt}\n"
                        "Return the JSON object only."
                    )
                }
            ],
        }
    ]
    for _ in range(POLL_DEPTH_CAP):
        resp = await call_gemini(
            http,
            settings,
            history,
            tools=tools,
            system=WATCH_POLL_SYSTEM,
            model=settings.gemini_watch_model,
            thinking_level="MINIMAL",
        )
        if not resp:
            return None
        parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if calls:
            history.append({"role": "model", "parts": parts})
            responses = []
            for fc in calls:
                # Only the narrow allow-list is declared, so the model can't
                # reach send_message or any state-mutating tool here.
                out = await execute_tool(fc["name"], fc.get("args", {}), ctx)
                responses.append(
                    {
                        "functionResponse": {
                            "name": fc["name"],
                            "response": {"content": out},
                        }
                    }
                )
            history.append({"role": "user", "parts": responses})
            continue
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        return _extract_json(text)
    return None  # exhausted depth without a verdict


# --------------------------------------------------------------------------- #
# Background checker (mirrors services/cron.py run_cron_checker)
# --------------------------------------------------------------------------- #


async def run_watch_checker(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    log.info("watch_checker.started")
    while True:
        try:
            await asyncio.sleep(settings.watch_check_interval_seconds)
            await _check_and_run(settings, http)
        except asyncio.CancelledError:
            log.info("watch_checker.cancelled")
            raise
        except Exception:
            log.exception("watch_checker.error")
            await asyncio.sleep(10)


async def _check_and_run(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    now = datetime.now(timezone.utc)
    async for session in get_session():
        due = (
            (
                await session.execute(
                    select(HalWatch)
                    .where(HalWatch.active == True, HalWatch.next_run_at <= now)  # noqa: E712
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for w in due:
            # Terminators checked BEFORE polling (no cost on a dead watch).
            if (
                now >= w.expires_at
                or w.polls_done >= w.max_polls
                or w.consecutive_fails >= BREAKER_FAILS
            ):
                w.active = False
                await session.flush()
                log.info("watch.expired", id=str(w.id), condition=w.condition[:50])
                continue

            verdict = await _poll(session, settings, http, w)
            w.last_run_at = now

            if verdict is None:
                w.consecutive_fails += 1
                w.next_run_at = now + timedelta(seconds=w.poll_every_seconds)
                log.info("watch.poll_failed", id=str(w.id), fails=w.consecutive_fails)
            elif verdict.get("condition_met"):
                to = w.chat_id if (w.is_group and w.chat_id) else w.phone
                obs = (verdict.get("observation") or "").strip()
                msg = w.notify + (f"\n{obs}" if obs else "")
                from hal_orchestrator.services.delivery import enqueue

                await enqueue(
                    session,
                    to=to,
                    text=msg,
                    idempotency_key=f"watch:{w.id}",
                )
                w.active = False
                # Record the observation that TRIGGERED the fire (not just the
                # last miss), so the row reflects why it fired.
                if obs:
                    w.last_observation = obs[:500]
                log.info("watch.fired", id=str(w.id), to=to, condition=w.condition[:50])
            elif verdict.get("terminal"):
                w.active = False
                log.info("watch.terminal", id=str(w.id), condition=w.condition[:50])
            else:
                w.consecutive_fails = 0
                w.polls_done += 1
                w.last_observation = (verdict.get("observation") or "")[:500]
                w.next_run_at = now + timedelta(seconds=w.poll_every_seconds)
            await session.flush()
        await session.commit()
