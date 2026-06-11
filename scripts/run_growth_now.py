"""Manually trigger one growth-loop run (GROWTH.md) outside the 3am window.

Grades ungraded turns from the last ~26h, builds the scorecard, verifies
playbook hypotheses, runs synthesis, publishes, and texts the admin digest
(via the outbox, drained by the bridge).

Usage:
  DATABASE_URL=postgresql+asyncpg://... GEMINI_API_KEY=... HAL_ADMIN_PHONE=+1... \
    python scripts/run_growth_now.py
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


async def main() -> None:
    if not os.environ.get("DATABASE_URL") or not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set DATABASE_URL and GEMINI_API_KEY")

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
