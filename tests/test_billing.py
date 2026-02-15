"""Tests for billing ledger and hold logic.

These tests require a running PostgreSQL database. They use the fixtures from
conftest.py which provide transactional test sessions.
"""

import uuid

import pytest

from ag_common.errors import InsufficientFundsError, NotFoundError
from ag_db.models import LedgerAccount


# Import the service modules — these will be tested against a real DB
pytestmark = pytest.mark.asyncio


async def test_deposit(session, test_consumer, consumer_ledger_accounts):
    """Test that deposit() credits the consumer balance."""
    from billing.services.ledger import deposit, get_balance

    balance_acct = consumer_ledger_accounts["consumer_balance"]
    assert balance_acct.balance_cents == 0

    await deposit(session, test_consumer.id, 1000, stripe_payment_intent_id="pi_test_123")
    await session.flush()

    balance = await get_balance(session, test_consumer.id)
    assert balance == 1000


async def test_place_hold(session, test_consumer, consumer_ledger_accounts):
    """Test placing a billing hold."""
    from billing.services.ledger import deposit
    from billing.services.holds import place_hold

    # Deposit funds first
    await deposit(session, test_consumer.id, 1000, stripe_payment_intent_id="pi_test_hold")
    await session.flush()

    # Place hold
    hold = await place_hold(session, test_consumer.id, 500)
    await session.flush()

    assert hold.amount_cents == 500
    assert hold.status == "active"

    # Check balances
    await session.refresh(consumer_ledger_accounts["consumer_balance"])
    await session.refresh(consumer_ledger_accounts["held_funds"])
    assert consumer_ledger_accounts["consumer_balance"].balance_cents == 500
    assert consumer_ledger_accounts["held_funds"].balance_cents == 500


async def test_place_hold_insufficient_funds(session, test_consumer, consumer_ledger_accounts):
    """Test that placing a hold with insufficient funds raises an error."""
    from billing.services.holds import place_hold

    with pytest.raises(InsufficientFundsError):
        await place_hold(session, test_consumer.id, 500)


async def test_settle_hold(
    session, test_consumer, test_developer, consumer_ledger_accounts, developer_ledger_account
):
    """Test settling a hold distributes funds (80% developer, 20% platform)."""
    from billing.services.ledger import deposit
    from billing.services.holds import place_hold, settle_hold

    await deposit(session, test_consumer.id, 1000, stripe_payment_intent_id="pi_test_settle")
    await session.flush()

    hold = await place_hold(session, test_consumer.id, 100)
    await session.flush()

    settled = await settle_hold(session, hold.id, test_developer.id)
    await session.flush()

    assert settled.status == "settled"

    # Developer gets 80%
    await session.refresh(developer_ledger_account)
    assert developer_ledger_account.balance_cents == 80


async def test_release_hold(session, test_consumer, consumer_ledger_accounts):
    """Test releasing a hold refunds funds to the consumer."""
    from billing.services.ledger import deposit, get_balance
    from billing.services.holds import place_hold, release_hold

    await deposit(session, test_consumer.id, 1000, stripe_payment_intent_id="pi_test_release")
    await session.flush()

    hold = await place_hold(session, test_consumer.id, 500)
    await session.flush()

    released = await release_hold(session, hold.id)
    await session.flush()

    assert released.status == "released"

    balance = await get_balance(session, test_consumer.id)
    assert balance == 1000  # Full refund


async def test_settle_already_settled_hold(
    session, test_consumer, test_developer, consumer_ledger_accounts, developer_ledger_account
):
    """Test that settling an already-settled hold raises an error."""
    from billing.services.ledger import deposit
    from billing.services.holds import place_hold, settle_hold

    await deposit(session, test_consumer.id, 1000, stripe_payment_intent_id="pi_test_double")
    await session.flush()

    hold = await place_hold(session, test_consumer.id, 100)
    await session.flush()

    await settle_hold(session, hold.id, test_developer.id)
    await session.flush()

    with pytest.raises(NotFoundError):
        await settle_hold(session, hold.id, test_developer.id)
