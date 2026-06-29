"""Manually trigger one growth-loop run (GROWTH.md) outside the 3am window.

Grades ungraded turns from the last ~26h, builds the scorecard, verifies
playbook hypotheses, runs synthesis, publishes, and texts the admin digest
(via the outbox, drained by the bridge).

Usage:
  DATABASE_URL=postgresql+asyncpg://... GEMINI_API_KEY=... HAL_ADMIN_PHONE=+1... \
    python scripts/run_growth_now.py [peek]

DATABASE_PUBLIC_URL (plain postgresql://, as Railway provides it) is accepted
as a fallback and normalized to the asyncpg driver.

`peek` is read-only: it lists the ungraded turns in the grading window
(user text, tools used, reply, status) without grading or synthesizing —
use it to inspect a trajectory before deciding to burn today's run
(a manual run records a reflection, so the next 3am run skips itself).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-common"))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "services", "hal-orchestrator")
)


def _normalize_db_url() -> None:
    """Allow DATABASE_PUBLIC_URL (plain postgresql://) as a fallback."""
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL") or ""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
    if url:
        os.environ["DATABASE_URL"] = url


async def peek() -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select
    from ag_db.models import HalTurn
    from ag_db.session import create_engine_and_session
    from hal_orchestrator.services.growth import GRADE_LOOKBACK_HOURS

    _, Session = create_engine_and_session(os.environ["DATABASE_URL"])
    since = datetime.now(timezone.utc) - timedelta(hours=GRADE_LOOKBACK_HOURS)
    async with Session() as session:
        rows = (
            (
                await session.execute(
                    select(HalTurn)
                    .where(HalTurn.graded_at.is_(None), HalTurn.created_at >= since)
                    .order_by(HalTurn.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
    print(f"{len(rows)} ungraded turn(s) in the {GRADE_LOOKBACK_HOURS}h window:\n")
    for t in rows:
        tools = [s.get("tool") for s in (t.steps or []) if isinstance(s, dict)]
        print(f"[{t.created_at:%m-%d %H:%M} UTC] silo={t.phone} status={t.status}")
        print(f"  user:  {(t.user_text or '')[:160]!r}")
        print(f"  tools: {tools}")
        print(f"  reply: {(t.reply or '')[:240]!r}\n")


async def main() -> None:
    _normalize_db_url()
    if not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATABASE_URL (or DATABASE_PUBLIC_URL)")

    if len(sys.argv) > 1 and sys.argv[1] == "peek":
        await peek()
        return

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY")

    import httpx
    from ag_common.config import HalOrchestratorConfig
    from ag_db.session import create_engine_and_session
    from ag_db import session as db_session

    from hal_orchestrator.services.growth import run_growth

    settings = HalOrchestratorConfig()
    create_engine_and_session(settings.database_url)
    Session = db_session._session_factory

    async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as http:
        async with Session() as session:
            report = await run_growth(session, settings, http)

    if report is None:
        print("nothing to grade")
        return
    print(json.dumps(report, indent=2, default=str))

    # The outbox is in-process here, so the admin digest queued by run_growth
    # would be lost — print it instead so the operator sees it.
    import hal_orchestrator.state as state

    while not state.outbox.empty():
        msg = state.outbox.get_nowait()
        print(f"\n--- queued message to {msg['to']} (NOT sent in manual mode) ---")
        print(msg["text"])


if __name__ == "__main__":
    asyncio.run(main())
