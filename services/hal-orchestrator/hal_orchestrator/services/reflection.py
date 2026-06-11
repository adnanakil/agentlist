"""Nightly self-improvement reflection.

Once a night (low-traffic window) HAL steps back from individual tasks and reads
its history in AGGREGATE — recent task trajectories plus friction signals (a
stubbed tool was requested, a turn hit the iteration cap, a tool errored) — and:

  1. AUTO-CREATES high-confidence reusable SKILLS as SHARED skills (everyone
     benefits; the curator keeps them tidy). Skills are safe to self-author —
     they're prompt templates, not code.
  2. PROPOSES new FEATURES/capabilities (ranked, with rationale + a build sketch)
     grounded in real demand — and texts the admin a concise digest. Features =
     code, so these are proposals for a human to greenlight, never auto-built.

Privacy: this reads across silos, so trajectory goals are PII-redacted before the
model sees them and the model is told to output only ANONYMIZED aggregate
patterns — never one user's private request.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalFrictionEvent, HalReflection, HalSkillTrajectory
from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.services.gemini import call_gemini

log = structlog.get_logger()

ET = ZoneInfo("America/New_York")
RUN_HOUR_ET = 3          # ~3am local
CHECK_INTERVAL_SECONDS = 60 * 30
LOOKBACK_DAYS = 7
MAX_TRAJECTORIES = 60
MAX_NEW_SKILLS_PER_NIGHT = 3

_PII = [
    (re.compile(r"\+?\d[\d\-\(\)\s]{7,}\d"), "<phone>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
]


def _redact(text: str) -> str:
    out = text or ""
    for rx, repl in _PII:
        out = rx.sub(repl, out)
    return out[:300]


REFLECT_PROMPT = """\
You are HAL's nightly self-improvement engine. You read HAL's recent activity in
AGGREGATE and decide how HAL should get better. You are given JSON: recent task
TRAJECTORIES (goal + tool steps), and FRICTION counts (stub_tool = a not-yet-built
capability was requested; stuck = HAL hit its step limit; tool_error).

Produce two things:

1. SHARED SKILLS to auto-create — reusable, multi-step WORKFLOW templates that
   recur across trajectories and would help many users. Be conservative and
   GENERALIZED (no user specifics). Only propose genuinely reusable procedures;
   most nights this may be empty.

2. FEATURE proposals — new capabilities HAL should BUILD, grounded in the
   evidence (especially repeated stub_tool requests = real unmet demand, and
   stuck/error clusters = gaps). Rank by impact. For each: the problem, the
   evidence (cite the aggregate signal, e.g. "resy requested 11x"), and a short
   build sketch. These are proposals for a human to build.

PRIVACY: output only anonymized AGGREGATE patterns. Never quote or reveal an
individual user's private request.

Output STRICT JSON only:
{
  "summary": "2-3 sentence overview of what you noticed",
  "shared_skills": [
    {"name":"kebab-name","description":"one line","keywords":["..."],"body":"reusable instruction template"}
  ],
  "features": [
    {"title":"...","problem":"...","evidence":"...","sketch":"...","priority":"high|medium|low"}
  ]
}
If nothing is worth proposing, use empty arrays."""


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        if start == -1:
            return {}
        text = text[start:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _gather(session: AsyncSession) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    trows = (
        await session.execute(
            select(HalSkillTrajectory)
            .where(HalSkillTrajectory.created_at >= since)
            .order_by(HalSkillTrajectory.created_at.desc())
            .limit(MAX_TRAJECTORIES)
        )
    ).scalars().all()
    trajectories = [
        {
            "goal": _redact(t.goal),
            "tools": [s.get("tool") for s in (t.steps or []) if isinstance(s, dict)],
        }
        for t in trows
    ]

    frows = (
        await session.execute(
            select(HalFrictionEvent.kind, HalFrictionEvent.detail, func.count())
            .where(HalFrictionEvent.created_at >= since)
            .group_by(HalFrictionEvent.kind, HalFrictionEvent.detail)
            .order_by(func.count().desc())
            .limit(40)
        )
    ).all()
    friction = [
        {"kind": k, "detail": _redact(d or ""), "count": int(c)} for k, d, c in frows
    ]
    return {"trajectories": trajectories, "friction": friction}


async def _reflect_pass(
    session: AsyncSession, settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> dict | None:
    data = await _gather(session)
    if not data["trajectories"] and not data["friction"]:
        log.info("reflection.nothing_to_do")
        return None

    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": json.dumps(data, indent=2)}]}],
        system=REFLECT_PROMPT,
        model=settings.gemini_flash_model,
        max_output_tokens=8192,
    )
    if not resp:
        return None
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return None
    obj = _parse_json("\n".join(p.get("text", "") for p in parts if "text" in p))

    # Auto-create high-confidence shared skills (capped, deduped by create()).
    created: list[str] = []
    for sk in (obj.get("shared_skills") or [])[:MAX_NEW_SKILLS_PER_NIGHT]:
        if not (sk.get("name") and sk.get("body")):
            continue
        result, err = await skills_svc.create(
            session,
            skills_svc.SHARED_OWNER,
            sk["name"],
            description=sk.get("description", "") or "",
            body=sk["body"],
            keywords=sk.get("keywords") or [],
        )
        if err is None:
            created.append(result["name"])
        else:
            log.info("reflection.skill_skipped", name=sk.get("name"), reason=err[:60])

    features = obj.get("features") or []
    report = {
        "summary": obj.get("summary", ""),
        "skills_created": created,
        "features": features,
        "signal": {
            "trajectories": len(data["trajectories"]),
            "friction": len(data["friction"]),
        },
    }
    session.add(HalReflection(summary=obj.get("summary", "")[:2000], report=report))
    await session.flush()

    # Text the admin a concise digest.
    if settings.admin_phone:
        await _notify_admin(settings, created, features, obj.get("summary", ""))

    await session.commit()
    log.info("reflection.done", skills_created=len(created), features=len(features))
    return report


async def _notify_admin(
    settings: HalOrchestratorConfig, created: list[str], features: list, summary: str
) -> None:
    import hal_orchestrator.state as state

    lines = ["🌙 HAL nightly self-review"]
    if summary:
        lines.append(summary[:300])
    if created:
        lines.append("\n✅ New skills auto-added: " + ", ".join(created))
    if features:
        lines.append("\n💡 Feature ideas:")
        for f in features[:5]:
            pri = (f.get("priority") or "").upper()[:1]
            lines.append(f"• [{pri}] {f.get('title', '?')} — {f.get('problem', '')[:80]}")
        lines.append("\n(Reply to discuss any; full report saved.)")
    if not created and not features:
        return
    await state.outbox.put({"to": settings.admin_phone, "text": "\n".join(lines)[:1400]})


async def _already_ran_today(session: AsyncSession) -> bool:
    today = datetime.now(ET).date()
    last = (
        await session.execute(
            select(func.max(HalReflection.created_at))
        )
    ).scalar_one_or_none()
    if last is None:
        return False
    return last.astimezone(ET).date() >= today


async def reflection_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.curator_enabled:
        return
    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("reflection.started", run_hour_et=RUN_HOUR_ET)
    try:
        while True:
            try:
                now = datetime.now(ET)
                if now.hour == RUN_HOUR_ET:
                    async with Session() as session:
                        if not await _already_ran_today(session):
                            log.info("reflection.running")
                            await _reflect_pass(session, settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reflection.tick_error")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("reflection.stopped")
        raise
