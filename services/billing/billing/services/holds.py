"""Hold management for invocation billing.

A *hold* temporarily moves funds from a consumer's balance into a held_funds
account while an agent invocation is in progress.  When the invocation
completes the hold is either *settled* (funds distributed to developer and
platform) or *released* (refunded to consumer).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.errors import InsufficientFundsError, NotFoundError
from ag_db.models import BillingHold, LedgerAccount, LedgerEntry

from billing.services.ledger import get_or_create_ledger_account

log = structlog.get_logger()

HOLD_EXPIRY_MINUTES = 15
DEVELOPER_SHARE = 0.80  # 80 %
PLATFORM_SHARE = 0.20  # 20 %


async def place_hold(
    session: AsyncSession,
    consumer_account_id: uuid.UUID,
    amount_cents: int,
    invocation_id: uuid.UUID | None = None,
) -> BillingHold:
    """Place a billing hold for an invocation.

    1. Lock the consumer's ``consumer_balance`` ledger account.
    2. Verify the balance covers the hold amount.
    3. Debit ``consumer_balance`` and credit ``held_funds``.
    4. Create a ``BillingHold`` record with a 15-minute expiry.
    5. Record a ``LedgerEntry`` of type ``hold``.
    """
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")

    # Lock consumer balance
    consumer_ledger = await get_or_create_ledger_account(
        session, consumer_account_id, "consumer_balance"
    )

    if consumer_ledger.balance_cents < amount_cents:
        raise InsufficientFundsError(
            f"Insufficient funds: need {amount_cents} cents, "
            f"have {consumer_ledger.balance_cents} cents",
            details={
                "required": amount_cents,
                "available": consumer_ledger.balance_cents,
            },
        )

    # Lock / create held_funds account (same owner)
    held_funds_ledger = await get_or_create_ledger_account(
        session, consumer_account_id, "held_funds"
    )

    # Move funds: consumer_balance -> held_funds
    consumer_ledger.balance_cents -= amount_cents
    held_funds_ledger.balance_cents += amount_cents

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=HOLD_EXPIRY_MINUTES)

    hold = BillingHold(
        consumer_ledger_account_id=consumer_ledger.id,
        held_funds_ledger_account_id=held_funds_ledger.id,
        invocation_id=invocation_id,
        amount_cents=amount_cents,
        status="active",
        expires_at=expires_at,
    )
    session.add(hold)
    await session.flush()

    entry = LedgerEntry(
        entry_type="hold",
        debit_account_id=consumer_ledger.id,
        credit_account_id=held_funds_ledger.id,
        amount_cents=amount_cents,
        invocation_id=invocation_id,
        description=f"Hold of {amount_cents} cents for invocation",
    )
    session.add(entry)
    await session.flush()

    log.info(
        "holds.placed",
        hold_id=str(hold.id),
        consumer_account_id=str(consumer_account_id),
        amount_cents=amount_cents,
        invocation_id=str(invocation_id) if invocation_id else None,
    )
    return hold


async def settle_hold(
    session: AsyncSession,
    hold_id: uuid.UUID,
    developer_account_id: uuid.UUID,
) -> BillingHold:
    """Settle a hold after a successful invocation.

    1. Load the active hold (FOR UPDATE).
    2. Debit ``held_funds``.
    3. Credit ``developer_earnings`` (80 %) and ``platform_revenue`` (20 %).
    4. Create LedgerEntries for the split.
    5. Mark the hold as settled.
    """
    hold = await _load_active_hold(session, hold_id)

    # Lock held_funds account
    held_funds_stmt = (
        select(LedgerAccount)
        .where(LedgerAccount.id == hold.held_funds_ledger_account_id)
        .with_for_update()
    )
    result = await session.execute(held_funds_stmt)
    held_funds_ledger = result.scalar_one()

    # Calculate split
    developer_amount = int(hold.amount_cents * DEVELOPER_SHARE)
    platform_amount = hold.amount_cents - developer_amount  # remainder to platform

    # Get / create developer_earnings and platform_revenue accounts
    developer_ledger = await get_or_create_ledger_account(
        session, developer_account_id, "developer_earnings"
    )
    platform_ledger = await get_or_create_ledger_account(
        session, developer_account_id, "platform_revenue"
    )

    # Debit held_funds
    held_funds_ledger.balance_cents -= hold.amount_cents

    # Credit developer_earnings
    developer_ledger.balance_cents += developer_amount

    # Credit platform_revenue
    platform_ledger.balance_cents += platform_amount

    # Ledger entries
    dev_entry = LedgerEntry(
        entry_type="settlement_developer",
        debit_account_id=held_funds_ledger.id,
        credit_account_id=developer_ledger.id,
        amount_cents=developer_amount,
        invocation_id=hold.invocation_id,
        description=f"Developer share ({int(DEVELOPER_SHARE * 100)}%) of {hold.amount_cents} cents",
    )
    session.add(dev_entry)

    platform_entry = LedgerEntry(
        entry_type="settlement_platform",
        debit_account_id=held_funds_ledger.id,
        credit_account_id=platform_ledger.id,
        amount_cents=platform_amount,
        invocation_id=hold.invocation_id,
        description=f"Platform share ({int(PLATFORM_SHARE * 100)}%) of {hold.amount_cents} cents",
    )
    session.add(platform_entry)

    hold.status = "settled"
    await session.flush()

    log.info(
        "holds.settled",
        hold_id=str(hold_id),
        developer_account_id=str(developer_account_id),
        developer_amount=developer_amount,
        platform_amount=platform_amount,
    )
    return hold


async def release_hold(
    session: AsyncSession,
    hold_id: uuid.UUID,
) -> BillingHold:
    """Release a hold — refund funds back to the consumer's balance.

    1. Load the active hold (FOR UPDATE).
    2. Debit ``held_funds``, credit ``consumer_balance``.
    3. Create a LedgerEntry of type ``release``.
    4. Mark the hold as released.
    """
    hold = await _load_active_hold(session, hold_id)

    # Lock held_funds
    held_stmt = (
        select(LedgerAccount)
        .where(LedgerAccount.id == hold.held_funds_ledger_account_id)
        .with_for_update()
    )
    held_result = await session.execute(held_stmt)
    held_funds_ledger = held_result.scalar_one()

    # Lock consumer balance
    consumer_stmt = (
        select(LedgerAccount)
        .where(LedgerAccount.id == hold.consumer_ledger_account_id)
        .with_for_update()
    )
    consumer_result = await session.execute(consumer_stmt)
    consumer_ledger = consumer_result.scalar_one()

    # Move funds: held_funds -> consumer_balance
    held_funds_ledger.balance_cents -= hold.amount_cents
    consumer_ledger.balance_cents += hold.amount_cents

    entry = LedgerEntry(
        entry_type="release",
        debit_account_id=held_funds_ledger.id,
        credit_account_id=consumer_ledger.id,
        amount_cents=hold.amount_cents,
        invocation_id=hold.invocation_id,
        description=f"Release of {hold.amount_cents} cents hold back to consumer",
    )
    session.add(entry)

    hold.status = "released"
    await session.flush()

    log.info(
        "holds.released",
        hold_id=str(hold_id),
        amount_cents=hold.amount_cents,
    )
    return hold


async def release_expired_holds(
    session: AsyncSession,
) -> list[BillingHold]:
    """Find and release all active holds that have expired."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(BillingHold)
        .where(
            BillingHold.status == "active",
            BillingHold.expires_at < now,
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    expired_holds = list(result.scalars().all())

    released: list[BillingHold] = []
    for hold in expired_holds:
        released_hold = await release_hold(session, hold.id)
        released.append(released_hold)

    if released:
        log.info("holds.expired_released", count=len(released))

    return released


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_active_hold(
    session: AsyncSession,
    hold_id: uuid.UUID,
) -> BillingHold:
    """Load a BillingHold that must exist and be active. Locks the row."""
    stmt = (
        select(BillingHold)
        .where(BillingHold.id == hold_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    hold = result.scalar_one_or_none()

    if hold is None:
        raise NotFoundError(f"Hold {hold_id} not found")

    if hold.status != "active":
        raise NotFoundError(
            f"Hold {hold_id} is not active (status={hold.status})",
            details={"hold_id": str(hold_id), "status": hold.status},
        )

    return hold
