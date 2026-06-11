"""Background curator that consolidates user skills.

Runs in a daemon asyncio task. Wakes every `curator_check_interval_seconds`,
and if (a) enough wall-clock time has passed since the last pass and
(b) the orchestrator has been quiet for `curator_min_idle_seconds`, asks the
auxiliary Gemini model to identify redundant/experimental skills and either
archive (auto-applied) or merge/rename (recorded for human review).

The curator only ever sees USER skills via list_user_skills_for_curator —
bundled skills are out of scope.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalCuratorState
from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.services.gemini import call_gemini

log = structlog.get_logger()

CURATOR_PROMPT = """\
You are HAL's skills Curator. You review HAL's user-created skills to
suggest consolidations. Output STRICT JSON only.

Rules:
- NEVER recommend deletion. Only `archive` (reversible).
- Built-in / bundled skills are NEVER in your input (so don't suggest changes to those).
- Prefer "leave alone" over aggressive change. Most entries should stay.
- Recommend `archive` only for clearly redundant duplicates or things that
  look like throwaway experiments (test names, single-word junk).
- Recommend `merge` only when two entries have near-identical purpose.

Output schema:
{
  "summary": "1-2 sentence overview of what you found",
  "actions": [
    {"kind": "archive", "id": "...", "reason": "..."},
    {"kind": "merge", "keep": "...", "absorb": "...", "reason": "..."},
    {"kind": "rename", "id": "...", "new_id": "...", "reason": "..."}
  ]
}

If nothing should change, return {"summary": "...", "actions": []}.
"""


# In-memory idle tracker. Updated by routes/message.py on each incoming msg.
_last_activity_ts = time.time()


def mark_activity() -> None:
    global _last_activity_ts
    _last_activity_ts = time.time()


def idle_seconds() -> float:
    return time.time() - _last_activity_ts


async def _load_state(session: AsyncSession) -> HalCuratorState:
    q = await session.execute(select(HalCuratorState).where(HalCuratorState.id == 1))
    row = q.scalar_one_or_none()
    if row is None:
        row = HalCuratorState(id=1)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def _should_run(session: AsyncSession, settings: HalOrchestratorConfig) -> bool:
    state = await _load_state(session)
    if state.paused:
        return False
    if state.last_run_at is None:
        return True
    elapsed = datetime.now(timezone.utc) - state.last_run_at
    return elapsed.total_seconds() >= settings.curator_interval_hours * 3600


def _parse_json_block(text: str) -> dict:
    """Extract the first JSON object from `text`, tolerant of ```json fences."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        if start == -1:
            return {"summary": "No JSON in response.", "actions": []}
        text = text[start:]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return {"summary": f"JSON parse failed: {e}", "actions": []}
    if not isinstance(obj, dict):
        return {"summary": "Non-object response.", "actions": []}
    obj.setdefault("summary", "")
    obj.setdefault("actions", [])
    clean: list[dict] = []
    for a in obj["actions"]:
        if isinstance(a, dict) and a.get("kind") in ("archive", "merge", "rename"):
            clean.append(a)
    obj["actions"] = clean
    return obj


async def _run_one_pass(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
) -> dict | None:
    user_skills = await skills_svc.list_user_skills_for_curator(session)
    if not user_skills:
        return {"summary": "No user skills to curate.", "actions": []}
    # Skills are per-silo; encode the owner into the id ("<phone>|<name>") so
    # archive actions land in the right silo and never cross owners.
    summary_payload = [
        {
            "id": f"{s.phone or ''}|{s.name}",
            "description": (s.description or "")[:200],
            "keywords": s.keywords,
        }
        for s in user_skills
    ]
    history = [
        {
            "role": "user",
            "parts": [{"text": json.dumps({"skills": summary_payload}, indent=2)}],
        }
    ]
    response = await call_gemini(
        http,
        settings,
        history,
        system=CURATOR_PROMPT,
        model=settings.gemini_flash_model,
    )
    if not response:
        return {"summary": "LLM call failed.", "actions": []}
    try:
        parts = response["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return {"summary": "Bad LLM response.", "actions": []}
    text = "\n".join(p.get("text", "") for p in parts if "text" in p)
    return _parse_json_block(text)


async def _apply_archives(session: AsyncSession, actions: list[dict]) -> int:
    applied = 0
    for a in actions:
        if a.get("kind") != "archive":
            continue
        rid = a.get("id")
        if not rid:
            continue
        # ids are "<phone>|<name>" (see _run_one_pass); tolerate bare names
        # from older curator output by treating the owner as empty.
        phone, _, name = rid.rpartition("|")
        _, err = await skills_svc.delete(
            session, phone, name, reason=f"curator: {a.get('reason', '')[:200]}"
        )
        if err is None:
            applied += 1
        else:
            log.warning("curator.archive_failed", id=rid, error=err)
    return applied


async def curator_loop(settings: HalOrchestratorConfig, http: httpx.AsyncClient) -> None:
    """Long-running background task. Cancelled on app shutdown."""
    if not settings.curator_enabled:
        log.info("curator.disabled")
        return

    log.info(
        "curator.started",
        check_interval=settings.curator_check_interval_seconds,
        interval_hours=settings.curator_interval_hours,
        min_idle_seconds=settings.curator_min_idle_seconds,
    )

    # Reuse the app-wide session factory created in main.py's lifespan.
    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    try:
        while True:
            try:
                idle = idle_seconds()
                if idle < settings.curator_min_idle_seconds:
                    await asyncio.sleep(settings.curator_check_interval_seconds)
                    continue
                async with Session() as session:
                    if not await _should_run(session, settings):
                        await asyncio.sleep(settings.curator_check_interval_seconds)
                        continue
                    log.info("curator.running", idle_seconds=idle)
                    report = await _run_one_pass(session, settings, http)
                    if report is None:
                        report = {"summary": "(no skills)", "actions": []}
                    applied = 0
                    if settings.curator_auto_apply:
                        applied = await _apply_archives(session, report.get("actions", []))
                    state = await _load_state(session)
                    state.last_run_at = datetime.now(timezone.utc)
                    state.run_count = (state.run_count or 0) + 1
                    state.last_summary = report.get("summary", "")[:1000]
                    state.last_actions_count = len(report.get("actions", []))
                    state.last_applied_count = applied
                    await session.commit()
                    log.info(
                        "curator.finished",
                        summary=state.last_summary[:120],
                        actions=state.last_actions_count,
                        applied=applied,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("curator.tick_error", error=str(e))
            await asyncio.sleep(settings.curator_check_interval_seconds)
    except asyncio.CancelledError:
        log.info("curator.stopped")
        raise
