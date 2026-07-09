"""Quarantine and promotion for global self-learning changes."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalLearningCandidate


async def stage(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict,
    reflection_id,
) -> HalLearningCandidate:
    candidate = HalLearningCandidate(
        kind=kind,
        payload=payload,
        status="pending",
        source_reflection_id=reflection_id,
    )
    session.add(candidate)
    await session.flush()
    return candidate


async def promote(
    session: AsyncSession,
    candidate: HalLearningCandidate,
    denylist: list[str],
) -> dict:
    if candidate.status != "pending":
        return {"error": f"candidate is {candidate.status}"}
    if candidate.kind == "playbook":
        from hal_orchestrator.services import playbook

        result = await playbook.apply_changes(
            session,
            candidate.payload,
            candidate.source_reflection_id,
            denylist,
        )
    elif candidate.kind == "shared_skill":
        from hal_orchestrator.services import playbook, skills

        payload = candidate.payload
        violation = playbook.lint_violation(
            f"{payload.get('description', '')} {payload.get('body', '')}", denylist
        )
        if violation:
            return {"error": violation}
        created, error = await skills.create(
            session,
            skills.SHARED_OWNER,
            payload.get("name", ""),
            description=payload.get("description", ""),
            body=payload.get("body", ""),
            keywords=payload.get("keywords") or [],
        )
        result = created if error is None else {"error": error}
    else:
        return {"error": f"unknown candidate kind: {candidate.kind}"}

    if isinstance(result, dict) and result.get("error"):
        return result
    candidate.status = "approved"
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.review_note = "promoted by admin"
    await session.flush()
    return result if isinstance(result, dict) else {"result": result}


async def reject(
    session: AsyncSession, candidate: HalLearningCandidate, note: str = ""
) -> None:
    candidate.status = "rejected"
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.review_note = note[:500]
    await session.flush()
