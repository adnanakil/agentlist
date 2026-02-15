"""Seed database with categories and optional test data.

Usage:
    uv run python scripts/seed_db.py
    uv run python scripts/seed_db.py --with-test-data
"""

import argparse
import asyncio
import hashlib
import uuid

from sqlalchemy import select

from ag_common.auth import generate_api_key
from ag_common.config import BaseConfig
from ag_db.models import Account, ApiKey, Category, LedgerAccount
from ag_db.session import create_engine_and_session

CATEGORIES = [
    ("data", "Data", "Agents for data processing, transformation, and analysis"),
    ("web", "Web", "Agents for web scraping, crawling, and web interactions"),
    ("text", "Text", "Agents for text processing, summarization, and NLP tasks"),
    ("code", "Code", "Agents for code formatting, analysis, and generation"),
    ("utilities", "Utilities", "General-purpose utility agents"),
    ("finance", "Finance", "Agents for financial data, calculations, and analysis"),
    ("communication", "Communication", "Agents for email, messaging, and notifications"),
    ("research", "Research", "Agents for research, information gathering, and synthesis"),
]


async def seed_categories(session) -> None:
    for slug, name, description in CATEGORIES:
        result = await session.execute(select(Category).where(Category.slug == slug))
        if not result.scalar_one_or_none():
            session.add(Category(
                id=uuid.uuid4(),
                name=name,
                slug=slug,
                description=description,
            ))
            print(f"  Created category: {name}")
        else:
            print(f"  Category exists: {name}")


async def seed_test_data(session) -> None:
    # Create test consumer
    consumer_email = "test-consumer@agentgate.dev"
    result = await session.execute(select(Account).where(Account.email == consumer_email))
    if not result.scalar_one_or_none():
        consumer = Account(
            id=uuid.uuid4(),
            email=consumer_email,
            password_hash=hashlib.sha256(b"testpassword").hexdigest(),
            role="consumer",
        )
        session.add(consumer)

        full_key, key_prefix, key_hash = generate_api_key()
        session.add(ApiKey(
            id=uuid.uuid4(),
            account_id=consumer.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
        ))

        for acct_type in ["consumer_balance", "held_funds"]:
            session.add(LedgerAccount(
                id=uuid.uuid4(),
                account_id=consumer.id,
                account_type=acct_type,
            ))

        print(f"  Created test consumer: {consumer_email}")
        print(f"  API Key: {full_key}")
    else:
        print(f"  Test consumer exists: {consumer_email}")

    # Create test developer
    dev_email = "test-developer@agentgate.dev"
    result = await session.execute(select(Account).where(Account.email == dev_email))
    if not result.scalar_one_or_none():
        developer = Account(
            id=uuid.uuid4(),
            email=dev_email,
            password_hash=hashlib.sha256(b"testpassword").hexdigest(),
            role="developer",
        )
        session.add(developer)

        full_key, key_prefix, key_hash = generate_api_key()
        session.add(ApiKey(
            id=uuid.uuid4(),
            account_id=developer.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
        ))

        session.add(LedgerAccount(
            id=uuid.uuid4(),
            account_id=developer.id,
            account_type="developer_earnings",
        ))

        print(f"  Created test developer: {dev_email}")
        print(f"  API Key: {full_key}")
    else:
        print(f"  Test developer exists: {dev_email}")

    # Create platform revenue account (admin)
    admin_email = "platform@agentgate.dev"
    result = await session.execute(select(Account).where(Account.email == admin_email))
    if not result.scalar_one_or_none():
        admin = Account(
            id=uuid.uuid4(),
            email=admin_email,
            password_hash=hashlib.sha256(b"adminpassword").hexdigest(),
            role="admin",
        )
        session.add(admin)

        session.add(LedgerAccount(
            id=uuid.uuid4(),
            account_id=admin.id,
            account_type="platform_revenue",
        ))

        print(f"  Created platform admin: {admin_email}")
    else:
        print(f"  Platform admin exists: {admin_email}")


async def main(with_test_data: bool) -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    async with session_factory() as session:
        print("Seeding categories...")
        await seed_categories(session)

        if with_test_data:
            print("\nSeeding test data...")
            await seed_test_data(session)

        await session.commit()
        print("\nDone!")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed AgentGate database")
    parser.add_argument("--with-test-data", action="store_true", help="Include test accounts")
    args = parser.parse_args()

    asyncio.run(main(args.with_test_data))
