"""Nightly growth loop — HAL assesses every turn and improves itself.

Replaces the old single-pass reflection (see GROWTH.md for the full design).
Pipeline, once a night at ~3am ET:

  A. GRADE (in-silo): one pro-model call per silo grades the day's turns
     (handled/partial/failed/na + failure taxonomy + conversation signals) and
     may emit user-specific lessons that go ONLY into that silo's profile.
     Full conversation content never leaves this phase.
  B. AGGREGATE (global, de-identified): scorecard — handled-rate, failures by
     category, deltas vs trailing week. Examples are redacted + name-scrubbed.
  D. VERIFY: re-check every live playbook entry's hypothesis against today's
     grades; 3 clean nights → verified, 3 failing nights → flagged for the
     synthesizer to revise/retire.
  C. SYNTHESIZE (global, pro model): playbook changes (each with a
     falsifiable hypothesis), shared skills, and feature-backlog upserts with
     accumulated evidence + build specs for high-priority items.
  E. PUBLISH: playbook changes pass the privacy lint; backlog threshold
     crossings + nightly scorecard digest text the admin. Sunday adds the
     weekly trend.

Failure taxonomy (each category maps to a fix channel):
  missing_tool         -> feature backlog (code)
  missing_knowledge    -> skill / playbook
  missing_data_access  -> feature backlog (integration)
  bad_judgment         -> playbook guidance
  external_block       -> playbook workaround ("ask for a screenshot")
  ambiguous_request    -> playbook clarify-pattern
  infra_error          -> feature backlog / ops
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
from ag_db.models import (
    HalFamily,
    HalFeatureRequest,
    HalFrictionEvent,
    HalReflection,
    HalTurn,
    HalUserProfile,
)
from hal_orchestrator.services import playbook as playbook_svc
from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.profiles import get_profile, update_profile

log = structlog.get_logger()

ET = ZoneInfo("America/New_York")
RUN_HOUR_ET = 3
CHECK_INTERVAL_SECONDS = 60 * 30

GRADE_LOOKBACK_HOURS = 26  # small overlap so a late run never skips turns
MAX_TURNS_PER_SILO = 120
MAX_FIELD_CHARS = 600
MAX_NEW_SKILLS_PER_NIGHT = 3
MAX_BACKLOG_UPDATES = 5
BACKLOG_NOTIFY_EVIDENCE = 3
VERIFY_NIGHTS = 3
MAX_SILO_LESSONS = 8

FAILURE_CATEGORIES = {
    "missing_tool",
    "missing_knowledge",
    "missing_data_access",
    "bad_judgment",
    "external_block",
    "ambiguous_request",
    "infra_error",
}

_PHONE_RX = re.compile(r"\+?\d[\d\-\(\)\s]{7,}\d")
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def parse_json_block(text: str) -> dict:
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


async def build_denylist(session: AsyncSession) -> list[str]:
    """Every known personal name/email across all silos — used to scrub
    aggregate inputs and lint global outputs."""
    names: set[str] = set()
    for (name,) in (await session.execute(select(HalUserProfile.name))).all():
        if name and len(name) >= 3:
            names.add(name.strip())
    for (email,) in (await session.execute(select(HalUserProfile.email))).all():
        if email:
            names.add(email.strip())
    for (baby,) in (await session.execute(select(HalFamily.baby_name))).all():
        if baby and len(baby) >= 3:
            names.add(baby.strip())
    return sorted(names)


def scrub(text: str, denylist: list[str], limit: int = 300) -> str:
    """De-identify text before it crosses into the global learning plane."""
    out = text or ""
    out = _PHONE_RX.sub("<phone>", out)
    out = _EMAIL_RX.sub("<email>", out)
    for name in denylist:
        out = re.sub(rf"\b{re.escape(name)}\b", "<name>", out, flags=re.I)
    return out[:limit]


async def _model_json(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    system: str,
    payload: dict,
) -> dict:
    """One JSON-payload model call → parsed JSON dict ({} on fail). Runs on the
    cheap BACKGROUND model — nightly grading/synthesis is always-on infra and
    shouldn't ride the (possibly premium) main loop's cost. gemini-3.5-flash is
    capable enough for grading; revisit if grade quality drops."""
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": json.dumps(payload, indent=1)}]}],
        system=system,
        model=settings.gemini_background_model,
        max_output_tokens=8192,
    )
    if not resp:
        return {}
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return {}
    return parse_json_block("\n".join(p.get("text", "") for p in parts if "text" in p))


# --------------------------------------------------------------------------- #
# Phase A — grade each silo's day (private; only verdicts leave)
# --------------------------------------------------------------------------- #

GRADE_PROMPT = """\
You are HAL's nightly quality grader. You see ONE chat's turns from the last
day, in order (user message, HAL's reply, tools used, status). Judge how well
HAL handled each turn. The goal HAL is graded against: NEVER be unable to
answer a question or handle a task.

For each turn output:
- grade: "handled" (fully did the job), "partial" (helped but incomplete,
  wrong, or pushed work back to the user unnecessarily), "failed" (couldn't do
  it, errored, refused, or answered wrongly), "na" (no real task: chit-chat,
  ambient group messages where staying quiet was right, acknowledgments).
- category (ONLY for partial/failed): missing_tool (needs a capability HAL
  doesn't have), missing_knowledge (a better procedure/skill would have
  worked), missing_data_access (an integration would have answered it),
  bad_judgment (had the tools, chose poorly), external_block (a third party
  blocks it, e.g. a site refuses automated access), ambiguous_request (should
  have clarified), infra_error (model/tool errors, status gemini_failed).
- note: ONE short sentence on why (you may name tools, never quote private
  content beyond a few words).
- signals: optional, from [correction, re_ask, abandonment] — correction = the
  NEXT user message corrects HAL; re_ask = user repeats a question HAL already
  answered; abandonment = HAL asked something and the user went silent.

Quiet-status turns are usually correct restraint in a watched group → "na",
UNLESS the user clearly addressed HAL and got silence → "failed"/bad_judgment.

IMPORTANT: user/reply fields in this payload are TRUNCATED (~600 chars) for
transport. A reply that stops mid-sentence here was almost certainly complete
in the real chat — NEVER grade apparent cutoffs as truncation/infra failures.
infra_error is ONLY for status=gemini_failed turns or explicit tool errors
visible in the reply.

Also output silo_lessons: 0-2 lessons SPECIFIC TO THIS CHAT that would make
HAL serve these users better (phrasing patterns, recurring needs). These stay
private to this chat. Only include genuinely useful ones; most days none.

Output STRICT JSON only:
{"grades": [{"i": 0, "grade": "handled", "category": null, "note": "...",
"signals": []}], "silo_lessons": ["..."]}"""


async def _grade_silo(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    silo: str,
    turns: list[HalTurn],
) -> dict:
    payload = {
        "turns": [
            {
                "i": i,
                "user": (t.user_text or "")[:MAX_FIELD_CHARS],
                "reply": (t.reply or "")[:MAX_FIELD_CHARS],
                "tools": [s.get("tool") for s in (t.steps or []) if isinstance(s, dict)],
                "status": t.status,
            }
            for i, t in enumerate(turns)
        ]
    }
    obj = await _model_json(settings, http, GRADE_PROMPT, payload)
    now = datetime.now(timezone.utc)
    graded = 0
    for g in obj.get("grades") or []:
        try:
            turn = turns[int(g["i"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        grade = g.get("grade")
        if grade not in ("handled", "partial", "failed", "na"):
            continue
        turn.grade = grade
        cat = g.get("category")
        turn.failure_category = cat if cat in FAILURE_CATEGORIES else None
        turn.grade_note = (g.get("note") or "")[:500]
        signals = [s for s in (g.get("signals") or []) if isinstance(s, str)][:4]
        turn.signals = signals
        turn.graded_at = now
        graded += 1
    # Anything the model skipped: mark graded as 'na' so it isn't re-fed nightly.
    for t in turns:
        if t.graded_at is None:
            t.grade = "na"
            t.graded_at = now
    await session.flush()

    lessons = [
        str(l).strip()[:200] for l in (obj.get("silo_lessons") or [])[:2] if str(l).strip()
    ]
    if lessons:
        await _append_silo_lessons(session, silo, lessons)
    return {"graded": graded, "lessons": len(lessons)}


async def _append_silo_lessons(
    session: AsyncSession, silo: str, lessons: list[str]
) -> None:
    """Write user-specific lessons into THIS silo's profile (capped section).
    These never enter the global plane."""
    profile = await get_profile(session, silo)
    notes = profile.get("notes") or ""
    header = "## Lessons (self-learned)"
    if header in notes:
        head, _, tail = notes.partition(header)
        existing = [l for l in tail.strip().splitlines() if l.strip().startswith("-")]
    else:
        head, existing = notes, []
    fresh = [f"- {l}" for l in lessons if l.lower() not in tail_lower(existing)]
    if not fresh:
        return
    kept = (existing + fresh)[-MAX_SILO_LESSONS:]
    new_notes = head.rstrip() + "\n\n" + header + "\n" + "\n".join(kept)
    await update_profile(session, silo, notes=new_notes.strip())


def tail_lower(lines: list[str]) -> str:
    return "\n".join(lines).lower()


async def run_grading(
    session: AsyncSession, settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=GRADE_LOOKBACK_HOURS)
    rows = (
        (
            await session.execute(
                select(HalTurn)
                .where(HalTurn.graded_at.is_(None), HalTurn.created_at >= since)
                .order_by(HalTurn.phone, HalTurn.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    by_silo: dict[str, list[HalTurn]] = {}
    for t in rows:
        by_silo.setdefault(t.phone, []).append(t)

    stats = {"silos": 0, "graded": 0, "lessons": 0}
    for silo, turns in by_silo.items():
        try:
            r = await _grade_silo(session, settings, http, silo, turns[:MAX_TURNS_PER_SILO])
            stats["silos"] += 1
            stats["graded"] += r["graded"]
            stats["lessons"] += r["lessons"]
        except Exception:
            log.exception("growth.grade_failed", silo=silo)
    return stats


# --------------------------------------------------------------------------- #
# Phase B — de-identified aggregate scorecard
# --------------------------------------------------------------------------- #


async def build_scorecard(
    session: AsyncSession, denylist: list[str]
) -> dict:
    now = datetime.now(timezone.utc)
    today_since = now - timedelta(hours=GRADE_LOOKBACK_HOURS)
    week_since = now - timedelta(days=8)

    async def counts(since: datetime, until: datetime) -> dict:
        rows = (
            await session.execute(
                select(HalTurn.grade, func.count())
                .where(
                    HalTurn.graded_at.isnot(None),
                    HalTurn.created_at >= since,
                    HalTurn.created_at < until,
                )
                .group_by(HalTurn.grade)
            )
        ).all()
        return {g: int(c) for g, c in rows}

    def rate(c: dict) -> float | None:
        denom = c.get("handled", 0) + c.get("partial", 0) + c.get("failed", 0)
        return round(c.get("handled", 0) / denom, 3) if denom else None

    today = await counts(today_since, now)
    week = await counts(week_since, today_since)

    cat_rows = (
        await session.execute(
            select(HalTurn.failure_category, func.count())
            .where(
                HalTurn.created_at >= today_since,
                HalTurn.grade.in_(["partial", "failed"]),
                HalTurn.failure_category.isnot(None),
            )
            .group_by(HalTurn.failure_category)
            .order_by(func.count().desc())
        )
    ).all()

    example_rows = (
        (
            await session.execute(
                select(HalTurn)
                .where(
                    HalTurn.created_at >= today_since,
                    HalTurn.grade.in_(["partial", "failed"]),
                )
                .order_by(HalTurn.created_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    failures = [
        {
            "category": t.failure_category,
            "grade": t.grade,
            "goal": scrub(t.user_text, denylist, 160),
            "note": scrub(t.grade_note, denylist, 200),
            "signals": t.signals or [],
        }
        for t in example_rows
    ]

    friction_rows = (
        await session.execute(
            select(HalFrictionEvent.kind, HalFrictionEvent.detail, func.count())
            .where(HalFrictionEvent.created_at >= today_since)
            .group_by(HalFrictionEvent.kind, HalFrictionEvent.detail)
            .order_by(func.count().desc())
            .limit(30)
        )
    ).all()
    friction = [
        {"kind": k, "detail": scrub(d or "", denylist, 120), "count": int(c)}
        for k, d, c in friction_rows
    ]

    return {
        "today": {"counts": today, "handled_rate": rate(today)},
        "trailing_week": {"counts": week, "handled_rate": rate(week)},
        "failures_by_category": [{"category": c, "count": int(n)} for c, n in cat_rows],
        "failure_examples": failures,
        "friction": friction,
    }


# --------------------------------------------------------------------------- #
# Phase D — verify playbook hypotheses against today's grades
# --------------------------------------------------------------------------- #


async def verify_playbook(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    today_since = now - timedelta(hours=GRADE_LOOKBACK_HOURS)
    verified: list[str] = []
    failing: list[dict] = []

    for entry in await playbook_svc.live_entries(session):
        if not entry.target_category:
            continue
        stmt = select(func.count()).select_from(HalTurn).where(
            HalTurn.created_at >= today_since,
            HalTurn.grade.in_(["partial", "failed"]),
            HalTurn.failure_category == entry.target_category,
        )
        recurrences = int((await session.execute(stmt)).scalar_one())
        if recurrences and entry.target_detail:
            # Narrow by detail substring when the entry targets something specific.
            rows = (
                (
                    await session.execute(
                        select(HalTurn.user_text, HalTurn.grade_note).where(
                            HalTurn.created_at >= today_since,
                            HalTurn.grade.in_(["partial", "failed"]),
                            HalTurn.failure_category == entry.target_category,
                        )
                    )
                )
                .all()
            )
            needle = entry.target_detail.lower()
            recurrences = sum(
                1 for u, n in rows if needle in (u or "").lower() + (n or "").lower()
            )
        if recurrences == 0:
            entry.clean_nights += 1
            entry.fail_nights = 0
            if entry.clean_nights >= VERIFY_NIGHTS and entry.status == "active":
                entry.status = "verified"
                verified.append(entry.content[:60])
        else:
            entry.fail_nights += 1
            entry.clean_nights = 0
            if entry.fail_nights >= VERIFY_NIGHTS and entry.status in ("active", "verified"):
                entry.status = "failing"
            if entry.status == "failing":
                failing.append(
                    {
                        "id": str(entry.id),
                        "content": entry.content,
                        "hypothesis": entry.hypothesis,
                        "recurrences_today": recurrences,
                    }
                )
        entry.updated_at = now
    await session.flush()
    playbook_svc.invalidate_cache()
    return {"verified": verified, "failing": failing}


# --------------------------------------------------------------------------- #
# Phase C — global synthesis (playbook / skills / backlog)
# --------------------------------------------------------------------------- #

SYNTH_PROMPT = """\
You are HAL's nightly self-improvement engine. HAL's goal: NEVER be unable to
answer a question or handle a task. You see a de-identified scorecard of
yesterday (grades, failure inventory with examples, friction), HAL's current
self-authored PLAYBOOK (operating notes injected into its prompt), entries
whose hypotheses are FAILING, the existing feature BACKLOG, and the tools HAL
has. Decide tonight's improvements.

1. playbook — operating notes that change HAL's behavior tomorrow.
   - add (≤3/night): ONE imperative sentence each, GENERIC (no names, no user
     specifics — they will be rejected). Each must target a failure seen in
     the data, with a hypothesis: which failure_category (and optional detail
     keyword) this should eliminate. Don't add notes for one-off flukes.
   - revise/retire: fix or remove FAILING entries (they didn't work) and
     near-duplicates. Quality over quantity — an empty night is fine.
2. shared_skills (≤3/night) — reusable multi-step workflow templates only if a
   recurring procedure is clearly visible. Most nights: none.
3. backlog — capabilities needing CODE (missing_tool / missing_data_access /
   infra clusters). Match to an existing backlog item by meaning (set
   match_id) so evidence accumulates; only create genuinely new items. For
   high-priority items (or ≥3 evidence), write spec: a build-ready paragraph
   (what, where it hooks in, data model, edge cases) a coding agent could
   implement directly.

PRIVACY: output only generic, anonymized patterns. Any name/number/email gets
the whole change rejected.

Output STRICT JSON only:
{"summary": "2-3 sentences",
 "playbook": {"add": [{"content": "...", "hypothesis": "...",
   "target_category": "...", "target_detail": "..."}],
  "revise": [{"id": "...", "content": "...", "hypothesis": "..."}],
  "retire": ["id"]},
 "shared_skills": [{"name": "kebab-name", "description": "...",
   "keywords": ["..."], "body": "..."}],
 "backlog": [{"match_id": null, "title": "...", "problem": "...",
   "evidence_signal": "...", "sketch": "...", "priority": "high|medium|low",
   "spec": ""}]}
Empty arrays when nothing is worth doing."""


async def run_synthesis(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    scorecard: dict,
    failing: list[dict],
    denylist: list[str],
    reflection_id,
) -> dict:
    from hal_orchestrator.prompts.tool_defs import MAIN_TOOLS
    from hal_orchestrator.tools.registry import STUBBED_TOOLS

    current_playbook = [
        {
            "id": str(e.id),
            "content": e.content,
            "status": e.status,
            "clean_nights": e.clean_nights,
            "fail_nights": e.fail_nights,
        }
        for e in await playbook_svc.live_entries(session)
    ]
    backlog_rows = (
        (
            await session.execute(
                select(HalFeatureRequest)
                .where(HalFeatureRequest.status.in_(["open", "notified", "greenlit"]))
                .order_by(HalFeatureRequest.evidence_count.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    payload = {
        "scorecard": scorecard,
        "playbook": current_playbook,
        "failing_entries": failing,
        "backlog": [
            {
                "id": str(b.id),
                "title": b.title,
                "evidence_count": b.evidence_count,
                "priority": b.priority,
                "status": b.status,
            }
            for b in backlog_rows
        ],
        "available_tools": sorted(
            d["name"] for d in MAIN_TOOLS[0]["function_declarations"]
        ),
        "stubbed_tools": sorted(STUBBED_TOOLS),
    }
    obj = await _model_json(settings, http, SYNTH_PROMPT, payload)
    if not obj:
        return {"summary": "", "playbook": {}, "skills_created": [], "backlog_changes": []}

    pb_report = await playbook_svc.apply_changes(
        session, obj.get("playbook") or {}, reflection_id, denylist
    )

    created: list[str] = []
    for sk in (obj.get("shared_skills") or [])[:MAX_NEW_SKILLS_PER_NIGHT]:
        if not (sk.get("name") and sk.get("body")):
            continue
        if playbook_svc.lint_violation(
            f"{sk.get('description', '')} {sk['body']}", denylist
        ):
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

    backlog_changes = await _upsert_backlog(
        session, obj.get("backlog") or [], {str(b.id): b for b in backlog_rows}, denylist
    )

    return {
        "summary": obj.get("summary", ""),
        "playbook": pb_report,
        "skills_created": created,
        "backlog_changes": backlog_changes,
    }


async def _upsert_backlog(
    session: AsyncSession,
    items: list[dict],
    existing: dict,
    denylist: list[str],
) -> list[dict]:
    now = datetime.now(timezone.utc)
    changes: list[dict] = []
    created_this_night: dict[str, HalFeatureRequest] = {}
    for item in items[:MAX_BACKLOG_UPDATES]:
        title = scrub(item.get("title") or "", denylist, 200).strip()
        if not title:
            continue
        signal = scrub(item.get("evidence_signal") or "", denylist, 200)
        row = existing.get(str(item.get("match_id") or ""))
        if row is None:
            # Dedupe by title even when the model misses match_id — including
            # against rows created earlier this same night.
            tl = title.lower()
            row = next(
                (b for b in existing.values() if b.title.lower() == tl), None
            ) or created_this_night.get(tl)
        if row is not None:
            row.evidence_count += 1
            row.last_seen = now
            row.evidence = (row.evidence or []) + [
                {"date": now.date().isoformat(), "signal": signal}
            ]
            if item.get("spec"):
                row.spec = scrub(item["spec"], denylist, 4000)
            order = {"low": 0, "medium": 1, "high": 2}
            if order.get(item.get("priority", ""), -1) > order.get(row.priority, 0):
                row.priority = item["priority"]
            changes.append({"title": row.title, "evidence_count": row.evidence_count, "new": False, "row": row})
        else:
            row = HalFeatureRequest(
                title=title,
                problem=scrub(item.get("problem") or "", denylist, 1000),
                evidence=[{"date": now.date().isoformat(), "signal": signal}],
                sketch=scrub(item.get("sketch") or "", denylist, 1000),
                spec=scrub(item.get("spec") or "", denylist, 4000),
                priority=item.get("priority") if item.get("priority") in ("high", "medium", "low") else "medium",
            )
            session.add(row)
            created_this_night[title.lower()] = row
            changes.append({"title": title, "evidence_count": 1, "new": True, "row": row})
    await session.flush()
    return changes


# --------------------------------------------------------------------------- #
# Phase E — publish + digest
# --------------------------------------------------------------------------- #


def _fmt_rate(r: float | None) -> str:
    return f"{round(r * 100)}%" if r is not None else "n/a"


async def _notify_admin(
    settings: HalOrchestratorConfig,
    scorecard: dict,
    synth: dict,
    verify: dict,
    backlog_pings: list[str],
    weekly: bool,
) -> None:
    import hal_orchestrator.state as state

    if not settings.admin_phone:
        return
    today = scorecard["today"]
    lines = ["🌙 HAL nightly growth report"]
    counts = today["counts"]
    real = counts.get("handled", 0) + counts.get("partial", 0) + counts.get("failed", 0)
    lines.append(
        f"Graded {real} task turns: {_fmt_rate(today['handled_rate'])} handled "
        f"(7d avg {_fmt_rate(scorecard['trailing_week']['handled_rate'])})"
    )
    cats = scorecard["failures_by_category"]
    if cats:
        lines.append(
            "Misses: " + ", ".join(f"{c['category']} ×{c['count']}" for c in cats[:4])
        )
    if synth.get("summary"):
        lines.append(synth["summary"][:280])
    pb = synth.get("playbook") or {}
    pb_bits = []
    if pb.get("added"):
        pb_bits.append(f"+{len(pb['added'])} notes")
    if pb.get("revised"):
        pb_bits.append(f"{len(pb['revised'])} revised")
    if pb.get("retired"):
        pb_bits.append(f"{len(pb['retired'])} retired")
    if verify.get("verified"):
        pb_bits.append(f"{len(verify['verified'])} verified ✓")
    if pb_bits:
        lines.append("Playbook: " + ", ".join(pb_bits))
    if synth.get("skills_created"):
        lines.append("New shared skills: " + ", ".join(synth["skills_created"]))
    for ping in backlog_pings[:3]:
        lines.append(f"💡 {ping}")
    if weekly:
        lines.append("(weekly trend in tonight's saved report — ask me for it)")
    await state.outbox.put({"to": settings.admin_phone, "text": "\n".join(lines)[:1400]})


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def run_growth(
    session: AsyncSession, settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> dict | None:
    denylist = await build_denylist(session)

    grade_stats = await run_grading(session, settings, http)
    if grade_stats["graded"] == 0 and grade_stats["silos"] == 0:
        log.info("growth.nothing_to_grade")
        return None

    scorecard = await build_scorecard(session, denylist)
    verify = await verify_playbook(session)

    reflection = HalReflection(summary="", report={})
    session.add(reflection)
    await session.flush()

    synth = await run_synthesis(
        session, settings, http, scorecard, verify["failing"], denylist, reflection.id
    )

    # Backlog notification: new high-priority, or evidence crossing threshold.
    now = datetime.now(timezone.utc)
    pings: list[str] = []
    for ch in synth.get("backlog_changes") or []:
        row = ch.pop("row", None)
        if row is None:
            continue
        crossed = row.evidence_count >= BACKLOG_NOTIFY_EVIDENCE and row.status == "open"
        if (ch["new"] and row.priority == "high") or crossed:
            row.status = "notified"
            row.notified_at = now
            pings.append(
                f"{row.title} ({row.evidence_count}x{' — spec drafted' if row.spec else ''})"
            )

    report = {
        "grading": grade_stats,
        "scorecard": scorecard,
        "verify": {"verified": verify["verified"], "failing": [f["content"][:80] for f in verify["failing"]]},
        "synthesis": {k: v for k, v in synth.items() if k != "backlog_changes"},
        "backlog": [
            {k: v for k, v in ch.items() if k != "row"}
            for ch in synth.get("backlog_changes") or []
        ],
    }
    reflection.summary = (synth.get("summary") or "")[:2000]
    reflection.report = report

    weekly = datetime.now(ET).weekday() == 6
    await _notify_admin(settings, scorecard, synth, verify, pings, weekly)
    await session.commit()
    log.info(
        "growth.done",
        graded=grade_stats["graded"],
        handled_rate=scorecard["today"]["handled_rate"],
        playbook_added=len((synth.get("playbook") or {}).get("added", [])),
    )
    return report


async def _already_ran_today(session: AsyncSession) -> bool:
    today = datetime.now(ET).date()
    last = (
        await session.execute(select(func.max(HalReflection.created_at)))
    ).scalar_one_or_none()
    return last is not None and last.astimezone(ET).date() >= today


async def growth_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.curator_enabled:
        return
    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("growth.started", run_hour_et=RUN_HOUR_ET)
    try:
        while True:
            try:
                now = datetime.now(ET)
                if now.hour == RUN_HOUR_ET:
                    async with Session() as session:
                        if not await _already_ran_today(session):
                            log.info("growth.running")
                            await run_growth(session, settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("growth.tick_error")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("growth.stopped")
        raise
