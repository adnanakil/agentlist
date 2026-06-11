"""Auto-skill creation — HAL learns reusable workflows from what it actually did.

When a turn completes with several tool calls, the route captures the trajectory
(goal + tool steps + outcome) into hal_skill_trajectories. This daemon later
asks the model whether that trajectory is a genuinely reusable multi-step
workflow and, if so, authors a per-silo SKILL (generalized, deduped against
existing skills). The skills curator then keeps the set tidy over time.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalSkillTrajectory
from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.services.curator import idle_seconds
from hal_orchestrator.services.gemini import call_gemini

log = structlog.get_logger()

# Capture trajectories with at least this many tool calls (multi-step tasks).
CAPTURE_MIN_TOOL_CALLS = 5

SYNTH_INTERVAL_SECONDS = 60 * 60  # hourly
SYNTH_MIN_IDLE_SECONDS = 120
SYNTH_BATCH = 5

SYNTH_PROMPT = """\
You decide whether a completed task should become a reusable SKILL for an AI
personal assistant, and if so, you author it.

You are given JSON: the USER GOAL, the TOOL STEPS the assistant took, the
OUTCOME, and the assistant's EXISTING SKILLS.

Save a skill ONLY if the task is a genuinely reusable, multi-step WORKFLOW the
user is likely to want again (e.g. a recurring research → compare → book
procedure, a custom summarize-and-format routine). Do NOT save: one-off
questions, simple single-tool lookups, anything already covered by an existing
skill, or anything overfit to one-time specifics. Be conservative — most
trajectories should NOT become skills.

If you do save it, GENERALIZE: turn the specific run into a reusable procedure,
parameterizing the one-off details. The body is the instruction template the
assistant will read and follow next time.

Output STRICT JSON only, no prose:
{"save": true|false, "reason": "...", "name": "kebab-case-name",
 "description": "one line", "keywords": ["..."],
 "body": "the reusable instruction template"}
If save is false, the other fields may be empty."""


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        if start == -1:
            return {"save": False}
        text = text[start:]
    try:
        # raw_decode parses the first JSON value and tolerates trailing text.
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj if isinstance(obj, dict) else {"save": False}
    except json.JSONDecodeError:
        return {"save": False}


async def capture_trajectory(
    session: AsyncSession, phone: str, goal: str, steps: list, outcome: str
) -> None:
    """Record a completed multi-tool task for later distillation. Best-effort;
    the caller wraps this so it can never break the live reply."""
    if not steps:
        return
    session.add(
        HalSkillTrajectory(
            phone=phone,
            goal=(goal or "")[:1000],
            steps=steps[:50],
            outcome=(outcome or "")[:1000],
        )
    )
    await session.flush()


async def _synthesize_one(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    traj: HalSkillTrajectory,
) -> None:
    existing = await skills_svc.list_skills(session, traj.phone)
    payload = json.dumps(
        {
            "goal": traj.goal,
            "steps": traj.steps,
            "outcome": traj.outcome,
            "existing_skills": [
                {"name": s.name, "description": s.description} for s in existing
            ],
        },
        indent=2,
    )
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": payload}]}],
        system=SYNTH_PROMPT,
        model=settings.gemini_flash_model,
    )
    if not resp:
        return
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return
    obj = _parse_json("\n".join(p.get("text", "") for p in parts if "text" in p))

    if obj.get("save") and obj.get("name") and obj.get("body"):
        result, err = await skills_svc.create(
            session,
            traj.phone,
            obj["name"],
            description=obj.get("description", "") or "",
            body=obj["body"],
            keywords=obj.get("keywords") or [],
        )
        if err is None:
            log.info("synth.skill_created", phone=traj.phone, name=result["name"])
        else:
            log.info("synth.skill_skipped", phone=traj.phone, reason=err[:80])


async def _synth_pass(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
) -> None:
    stmt = (
        select(HalSkillTrajectory)
        .where(HalSkillTrajectory.processed == False)  # noqa: E712
        .order_by(HalSkillTrajectory.created_at.desc())
        .limit(SYNTH_BATCH)
    )
    trajs = (await session.execute(stmt)).scalars().all()
    for traj in trajs:
        try:
            await _synthesize_one(session, settings, http, traj)
        except Exception:
            log.exception("synth.one_failed", traj_id=str(traj.id))
        traj.processed = True  # mark processed regardless so it can't get stuck
    await session.commit()


async def skill_synthesizer_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.curator_enabled:
        return
    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("synth.started", interval=SYNTH_INTERVAL_SECONDS)
    try:
        while True:
            try:
                if idle_seconds() >= SYNTH_MIN_IDLE_SECONDS:
                    async with Session() as session:
                        await _synth_pass(session, settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("synth.tick_error")
            await asyncio.sleep(SYNTH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("synth.stopped")
        raise
