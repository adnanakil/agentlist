"""Double-entry bookkeeping service.

Every balance mutation is recorded as a LedgerEntry with both a debit and a
credit account, ensuring the books always balance.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import LedgerAccount, LedgerEntry

log = structlog.get_logger()


async def get_or_create_ledger_account(
    session: AsyncSession,
    account_id: uuid.UUID,
    account_type: str,
) -> LedgerAccount:
    """Return an existing LedgerAccount or create one with zero balance.

    Uses SELECT ... FOR UPDATE so concurrent callers on the same row will
    serialize properly.
    """
    stmt = (
        select(LedgerAccount)
        .where(
            LedgerAccount.account_id == account_id,
            LedgerAccount.account_type == account_type,
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    ledger_account = result.scalar_one_or_none()

    if ledger_account is None:
        ledger_account = LedgerAccount(
            account_id=account_id,
            account_type=account_type,
            balance_cents=0,
        )
        session.add(ledger_account)
        await session.flush()
        log.info(
            "ledger.account_created",
            account_id=str(account_id),
            account_type=account_type,
        )

    return ledger_account


async def deposit(
    session: AsyncSession,
    account_id: uuid.UUID,
    amount_cents: int,
    stripe_payment_intent_id: str | None = None,
) -> LedgerEntry:
    """Credit the consumer_balance for *account_id* by *amount_cents*.

    A deposit is modelled as:
        debit  = consumer_balance  (increases asset)
        credit = consumer_balance  (same account — external money in)

    We store the stripe payment intent for reconciliation / idempotency.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")

    # Lock the ledger account row for the duration of the transaction
    ledger_account = await get_or_create_ledger_account(
        session, account_id, "consumer_balance"
    )

    ledger_account.balance_cents += amount_cents

    entry = LedgerEntry(
        entry_type="deposit",
        debit_account_id=ledger_account.id,
        credit_account_id=ledger_account.id,
        amount_cents=amount_cents,
        stripe_payment_intent_id=stripe_payment_intent_id,
        description=f"Deposit of {amount_cents} cents via Stripe",
    )
    session.add(entry)
    await session.flush()

    log.info(
        "ledger.deposit",
        account_id=str(account_id),
        amount_cents=amount_cents,
        new_balance=ledger_account.balance_cents,
        stripe_pi=stripe_payment_intent_id,
    )
    return entry


async def get_balance(
    session: AsyncSession,
    account_id: uuid.UUID,
) -> int:
    """Return the current balance_cents for the consumer_balance account."""
    stmt = select(LedgerAccount.balance_cents).where(
        LedgerAccount.account_id == account_id,
        LedgerAccount.account_type == "consumer_balance",
    )
    result = await session.execute(stmt)
    balance = result.scalar_one_or_none()
    return balance if balance is not None else 0


async def get_transaction_history(
    session: AsyncSession,
    account_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LedgerEntry], int]:
    """Return recent LedgerEntries involving *account_id* and a total count.

    We find all ledger_account IDs that belong to the account, then fetch
    entries where either the debit or credit side references one of them.
    """
    # First, find all ledger account IDs belonging to the account
    acct_stmt = select(LedgerAccount.id).where(
        LedgerAccount.account_id == account_id,
    )
    acct_result = await session.execute(acct_stmt)
    ledger_account_ids = list(acct_result.scalars().all())

    if not ledger_account_ids:
        return [], 0

    # Total count
    count_stmt = (
        select(func.count())
        .select_from(LedgerEntry)
        .where(
            (LedgerEntry.debit_account_id.in_(ledger_account_ids))
            | (LedgerEntry.credit_account_id.in_(ledger_account_ids))
        )
    )
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    # Paginated entries, newest first
    entries_stmt = (
        select(LedgerEntry)
        .where(
            (LedgerEntry.debit_account_id.in_(ledger_account_ids))
            | (LedgerEntry.credit_account_id.in_(ledger_account_ids))
        )
        .order_by(LedgerEntry.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    entries_result = await session.execute(entries_stmt)
    entries = list(entries_result.scalars().all())

    return entries, total
