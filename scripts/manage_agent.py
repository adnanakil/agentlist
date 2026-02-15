"""CLI script to manage agents (approve, suspend, list).

Usage:
    uv run python scripts/manage_agent.py list
    uv run python scripts/manage_agent.py approve --slug echo
    uv run python scripts/manage_agent.py suspend --slug echo
"""

import argparse
import asyncio

from sqlalchemy import select, update

from ag_common.config import BaseConfig
from ag_db.models import Agent
from ag_db.session import create_engine_and_session


async def list_agents(status_filter: str | None) -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    async with session_factory() as session:
        query = select(Agent).order_by(Agent.created_at.desc())
        if status_filter:
            query = query.where(Agent.status == status_filter)
        result = await session.execute(query)
        agents = result.scalars().all()

        if not agents:
            print("No agents found.")
            return

        print(f"{'Slug':<25} {'Status':<12} {'Price':>8} {'Invocations':>12} {'Version'}")
        print("-" * 75)
        for a in agents:
            print(
                f"{a.slug:<25} {a.status:<12} {a.price_per_call_cents:>6}¢  "
                f"{a.total_invocations:>12} {a.version}"
            )

    await engine.dispose()


async def update_agent_status(slug: str, new_status: str) -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    async with session_factory() as session:
        result = await session.execute(select(Agent).where(Agent.slug == slug))
        agent = result.scalar_one_or_none()
        if not agent:
            print(f"Error: Agent '{slug}' not found")
            return

        old_status = agent.status
        await session.execute(
            update(Agent).where(Agent.slug == slug).values(status=new_status)
        )
        await session.commit()
        print(f"Agent '{slug}' status: {old_status} → {new_status}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage AgentGate agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_parser = subparsers.add_parser("list", help="List agents")
    list_parser.add_argument("--status", help="Filter by status")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Approve an agent")
    approve_parser.add_argument("--slug", required=True, help="Agent slug")

    # suspend
    suspend_parser = subparsers.add_parser("suspend", help="Suspend an agent")
    suspend_parser.add_argument("--slug", required=True, help="Agent slug")

    args = parser.parse_args()

    if args.command == "list":
        asyncio.run(list_agents(args.status))
    elif args.command == "approve":
        asyncio.run(update_agent_status(args.slug, "active"))
    elif args.command == "suspend":
        asyncio.run(update_agent_status(args.slug, "suspended"))


if __name__ == "__main__":
    main()
