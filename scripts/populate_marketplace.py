"""Populate the marketplace with developer accounts and agents.

Creates multiple developer accounts and distributes all agents from agents/
directory across them. Also creates a few consumer accounts with balances.

Usage:
    DATABASE_URL="..." uv run python scripts/populate_marketplace.py
"""

import asyncio
import hashlib
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select, update

from ag_common.auth import generate_api_key
from ag_common.config import BaseConfig
from ag_db.models import Account, Agent, ApiKey, Category, LedgerAccount
from ag_db.session import create_engine_and_session

AGENTS_DIR = Path(__file__).parent.parent / "agents"

# Developer personas — each "company" gets a subset of agents
DEVELOPERS = [
    {
        "email": "sarah@dataweave.io",
        "password": "dataweave2024",
        "company": "DataWeave",
        "agents": ["csv-analyzer", "json-transformer"],
    },
    {
        "email": "marcus@webtools.dev",
        "password": "webtools2024",
        "company": "WebTools",
        "agents": ["web-scraper", "markdown-converter"],
    },
    {
        "email": "priya@textcraft.ai",
        "password": "textcraft2024",
        "company": "TextCraft AI",
        "agents": ["text-summarizer", "word-counter"],
    },
    {
        "email": "jake@devutils.com",
        "password": "devutils2024",
        "company": "DevUtils",
        "agents": ["code-formatter", "regex-tester"],
    },
    {
        "email": "elena@securebytes.io",
        "password": "securebytes2024",
        "company": "SecureBytes",
        "agents": ["hash-generator", "base64-encoder"],
    },
    {
        "email": "omar@netops.tools",
        "password": "netops2024",
        "company": "NetOps",
        "agents": ["ip-lookup", "email-validator"],
    },
    {
        "email": "lisa@claudelabs.ai",
        "password": "claudelabs2024",
        "company": "Claude Labs",
        "agents": ["claude-assistant", "brainstorm"],
    },
    {
        "email": "nina@placewise.ai",
        "password": "placewise2024",
        "company": "PlaceWise",
        "agents": ["place-finder"],
    },
    {
        "email": "kai@pixelforge.io",
        "password": "pixelforge2024",
        "company": "PixelForge",
        "agents": ["image-generator"],
    },
    {
        "email": "sam@docshare.dev",
        "password": "docshare2024",
        "company": "DocShare",
        "agents": ["page-creator"],
    },
    {
        "email": "ava@scholarai.com",
        "password": "scholarai2024",
        "company": "Scholar AI",
        "agents": ["scholar"],
    },
    {
        "email": "tom@freshcart.io",
        "password": "freshcart2024",
        "company": "FreshCart",
        "agents": ["instacart-list", "instacart-recipe"],
    },
]

# Extra consumer accounts to add activity
CONSUMERS = [
    {"email": "demo@agentgate.dev", "password": "demopass2024", "balance_cents": 2500},
    {"email": "alex@startup.co", "password": "startup2024", "balance_cents": 1500},
    {"email": "maria@freelance.dev", "password": "freelance2024", "balance_cents": 500},
    {"email": "raj@techcorp.io", "password": "techcorp2024", "balance_cents": 5000},
]


def load_manifest(agent_path: Path) -> dict:
    with open(agent_path / "manifest.yaml") as f:
        return yaml.safe_load(f)


async def create_or_get_account(
    session, email: str, password: str, role: str
) -> tuple[Account, str | None]:
    """Create account if it doesn't exist. Returns (account, api_key_or_None)."""
    result = await session.execute(select(Account).where(Account.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        print(f"  Account exists: {email}")
        return existing, None

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    account = Account(
        id=uuid.uuid4(),
        email=email,
        password_hash=password_hash,
        role=role,
    )
    session.add(account)

    full_key, key_prefix, key_hash = generate_api_key()
    session.add(
        ApiKey(
            id=uuid.uuid4(),
            account_id=account.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
        )
    )

    if role == "consumer":
        ledger_types = ["consumer_balance", "held_funds"]
    else:
        ledger_types = ["developer_earnings"]

    for acct_type in ledger_types:
        session.add(
            LedgerAccount(
                id=uuid.uuid4(),
                account_id=account.id,
                account_type=acct_type,
            )
        )

    print(f"  Created {role}: {email} (key: {key_prefix}...)")
    return account, full_key


async def submit_agent_from_manifest(
    session, agent_slug: str, developer_id: uuid.UUID
) -> bool:
    """Submit an agent from its manifest. Returns True if created, False if exists."""
    # Check if already exists
    result = await session.execute(select(Agent).where(Agent.slug == agent_slug))
    if result.scalar_one_or_none():
        print(f"    Agent exists: {agent_slug}")
        return False

    agent_path = AGENTS_DIR / agent_slug
    if not agent_path.exists():
        print(f"    Agent dir not found: {agent_slug}")
        return False

    manifest = load_manifest(agent_path)

    # Find category
    category_id = None
    category_slug = manifest.get("category")
    if category_slug:
        result = await session.execute(
            select(Category).where(Category.slug == category_slug)
        )
        cat = result.scalar_one_or_none()
        if cat:
            category_id = cat.id

    agent = Agent(
        id=uuid.uuid4(),
        developer_id=developer_id,
        category_id=category_id,
        slug=agent_slug,
        name=manifest["name"],
        description=manifest["description"],
        version=manifest["version"],
        runtime=manifest["runtime"],
        status="active",  # Auto-approve
        price_per_call_cents=manifest.get("price_per_call_cents", 0),
        input_schema=manifest.get("input_schema", {}),
        manifest=manifest,
        tags=manifest.get("tags", []),
        image_uri=f"agentgate-agent-{agent_slug}:latest",
        required_consumer_credentials=manifest.get("required_consumer_credentials", []),
    )
    session.add(agent)
    print(f"    Submitted + activated: {agent_slug} ({agent.price_per_call_cents}c/call)")
    return True


async def set_consumer_balance(session, account_id: uuid.UUID, balance_cents: int) -> None:
    """Set balance on a consumer's consumer_balance ledger account."""
    result = await session.execute(
        select(LedgerAccount).where(
            LedgerAccount.account_id == account_id,
            LedgerAccount.account_type == "consumer_balance",
        )
    )
    la = result.scalar_one_or_none()
    if la and la.balance_cents != balance_cents:
        await session.execute(
            update(LedgerAccount)
            .where(LedgerAccount.id == la.id)
            .values(balance_cents=balance_cents)
        )
        print(f"    Set balance: ${balance_cents / 100:.2f}")


async def main() -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    async with session_factory() as session:
        # --- Developer accounts + agents ---
        print("\n=== Creating developer accounts ===")
        for dev in DEVELOPERS:
            print(f"\n{dev['company']}:")
            account, api_key = await create_or_get_account(
                session, dev["email"], dev["password"], "developer"
            )
            for agent_slug in dev["agents"]:
                await submit_agent_from_manifest(session, agent_slug, account.id)

        # --- Also register echo under test-developer if not already ---
        print("\n=== Checking echo agent ===")
        result = await session.execute(
            select(Account).where(Account.email == "test-developer@agentgate.dev")
        )
        test_dev = result.scalar_one_or_none()
        if test_dev:
            await submit_agent_from_manifest(session, "echo", test_dev.id)

        # --- Consumer accounts ---
        print("\n=== Creating consumer accounts ===")
        for consumer in CONSUMERS:
            account, api_key = await create_or_get_account(
                session, consumer["email"], consumer["password"], "consumer"
            )
            await set_consumer_balance(session, account.id, consumer["balance_cents"])

        await session.commit()

        # --- Summary ---
        print("\n=== Marketplace Summary ===")
        result = await session.execute(select(Agent).order_by(Agent.slug))
        agents = result.scalars().all()
        print(f"\nTotal agents: {len(agents)}")
        print(f"{'Slug':<25} {'Status':<10} {'Price':>6} {'Developer ID'}")
        print("-" * 80)
        for a in agents:
            print(f"{a.slug:<25} {a.status:<10} {a.price_per_call_cents:>4}c   {a.developer_id}")

        result = await session.execute(select(Account).order_by(Account.email))
        accounts = result.scalars().all()
        print(f"\nTotal accounts: {len(accounts)}")
        print(f"{'Email':<35} {'Role':<12}")
        print("-" * 50)
        for acc in accounts:
            print(f"{acc.email:<35} {acc.role:<12}")

    await engine.dispose()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
