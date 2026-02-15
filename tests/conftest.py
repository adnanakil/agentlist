"""Shared test fixtures for AgentGate tests."""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ag_common.auth import generate_api_key
from ag_db.models import (
    Account,
    Agent,
    ApiKey,
    Base,
    Category,
    LedgerAccount,
)


TEST_DATABASE_URL = "postgresql+asyncpg://agentgate:agentgate@localhost:5432/agentgate_test"


@pytest.fixture(scope="session")
def event_loop():
    """Override the default event loop to be session-scoped."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test database engine."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional test session that rolls back after each test."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_consumer(session: AsyncSession) -> Account:
    """Create a test consumer account."""
    account = Account(
        id=uuid.uuid4(),
        email=f"consumer-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hashlib.sha256(b"testpassword").hexdigest(),
        role="consumer",
    )
    session.add(account)
    await session.flush()
    return account


@pytest_asyncio.fixture
async def test_developer(session: AsyncSession) -> Account:
    """Create a test developer account."""
    account = Account(
        id=uuid.uuid4(),
        email=f"developer-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hashlib.sha256(b"testpassword").hexdigest(),
        role="developer",
    )
    session.add(account)
    await session.flush()
    return account


@pytest_asyncio.fixture
async def consumer_api_key(session: AsyncSession, test_consumer: Account) -> str:
    """Create an API key for the test consumer and return the full key."""
    full_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        id=uuid.uuid4(),
        account_id=test_consumer.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    session.add(api_key)
    await session.flush()
    return full_key


@pytest_asyncio.fixture
async def consumer_ledger_accounts(
    session: AsyncSession, test_consumer: Account
) -> dict[str, LedgerAccount]:
    """Create consumer_balance and held_funds ledger accounts."""
    balance = LedgerAccount(
        id=uuid.uuid4(),
        account_id=test_consumer.id,
        account_type="consumer_balance",
        balance_cents=0,
    )
    held = LedgerAccount(
        id=uuid.uuid4(),
        account_id=test_consumer.id,
        account_type="held_funds",
        balance_cents=0,
    )
    session.add_all([balance, held])
    await session.flush()
    return {"consumer_balance": balance, "held_funds": held}


@pytest_asyncio.fixture
async def developer_ledger_account(
    session: AsyncSession, test_developer: Account
) -> LedgerAccount:
    """Create a developer_earnings ledger account."""
    earnings = LedgerAccount(
        id=uuid.uuid4(),
        account_id=test_developer.id,
        account_type="developer_earnings",
        balance_cents=0,
    )
    session.add(earnings)
    await session.flush()
    return earnings


@pytest_asyncio.fixture
async def test_category(session: AsyncSession) -> Category:
    """Create a test category."""
    cat = Category(
        id=uuid.uuid4(),
        name="Utilities",
        slug="utilities",
        description="General utilities",
    )
    session.add(cat)
    await session.flush()
    return cat


@pytest_asyncio.fixture
async def test_agent(
    session: AsyncSession, test_developer: Account, test_category: Category
) -> Agent:
    """Create a test agent."""
    agent = Agent(
        id=uuid.uuid4(),
        developer_id=test_developer.id,
        category_id=test_category.id,
        slug=f"test-agent-{uuid.uuid4().hex[:8]}",
        name="Test Agent",
        description="A test agent for unit tests",
        version="0.1.0",
        runtime="python",
        status="active",
        price_per_call_cents=5,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        manifest={"name": "test-agent", "version": "0.1.0", "description": "test", "runtime": "python", "entrypoint": "agent.py"},
        tags=["test"],
        image_uri="agentgate-agent-test:latest",
        total_invocations=10,
        success_rate=0.9,
        avg_latency_ms=100.0,
    )
    session.add(agent)
    await session.flush()
    return agent
