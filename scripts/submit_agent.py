"""CLI script to register an agent from a package directory.

Usage:
    uv run python scripts/submit_agent.py --path agents/echo --developer-email dev@example.com
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

from ag_common.config import BaseConfig
from ag_db.models import Account, Agent, Category
from ag_db.session import create_engine_and_session


def load_manifest(agent_path: Path) -> dict:
    manifest_path = agent_path / "manifest.yaml"
    if not manifest_path.exists():
        print(f"Error: manifest.yaml not found in {agent_path}")
        sys.exit(1)
    with open(manifest_path) as f:
        return yaml.safe_load(f)


async def submit_agent(agent_path: Path, developer_email: str) -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    manifest = load_manifest(agent_path)

    # Validate required fields
    required = ["name", "version", "description", "runtime", "entrypoint"]
    missing = [f for f in required if f not in manifest]
    if missing:
        print(f"Error: Missing manifest fields: {', '.join(missing)}")
        sys.exit(1)

    async with session_factory() as session:
        # Find developer account
        result = await session.execute(
            select(Account).where(Account.email == developer_email)
        )
        developer = result.scalar_one_or_none()
        if not developer:
            print(f"Error: Developer account not found: {developer_email}")
            sys.exit(1)

        # Find or skip category
        category_id = None
        category_slug = manifest.get("category")
        if category_slug:
            result = await session.execute(
                select(Category).where(Category.slug == category_slug)
            )
            cat = result.scalar_one_or_none()
            if cat:
                category_id = cat.id
            else:
                print(f"Warning: Category '{category_slug}' not found, skipping")

        # Check if agent slug exists
        slug = manifest["name"]
        result = await session.execute(select(Agent).where(Agent.slug == slug))
        if result.scalar_one_or_none():
            print(f"Error: Agent with slug '{slug}' already exists")
            sys.exit(1)

        # Create agent
        agent = Agent(
            id=uuid.uuid4(),
            developer_id=developer.id,
            category_id=category_id,
            slug=slug,
            name=manifest["name"],
            description=manifest["description"],
            version=manifest["version"],
            runtime=manifest["runtime"],
            status="review",
            price_per_call_cents=manifest.get("price_per_call_cents", 0),
            input_schema=manifest.get("input_schema", {}),
            manifest=manifest,
            tags=manifest.get("tags", []),
            image_uri=f"agentgate-agent-{slug}:latest",
        )
        session.add(agent)
        await session.commit()

        print(f"Agent submitted successfully!")
        print(f"  Agent ID:  {agent.id}")
        print(f"  Slug:      {agent.slug}")
        print(f"  Status:    {agent.status}")
        print(f"  Price:     {agent.price_per_call_cents} cents/call")
        print()
        print("The agent is in 'review' status. Use manage_agent.py to approve it.")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit an agent to AgentGate")
    parser.add_argument("--path", required=True, help="Path to agent package directory")
    parser.add_argument("--developer-email", required=True, help="Developer account email")
    args = parser.parse_args()

    asyncio.run(submit_agent(Path(args.path), args.developer_email))


if __name__ == "__main__":
    main()
