"""Internal routes for account balance and transaction history."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.errors import ValidationError
from ag_common.models import BalanceResponse, TransactionHistoryResponse, TransactionSummary
from ag_db.session import get_session

from billing.services import ledger

log = structlog.get_logger()
router = APIRouter()


def _parse_account_id(x_account_id: str | None = Header(None)) -> uuid.UUID:
    """Extract and validate the X-Account-ID header."""
    if not x_account_id:
        raise ValidationError("X-Account-ID header is required")
    try:
        return uuid.UUID(x_account_id)
    except ValueError:
        raise ValidationError("X-Account-ID must be a valid UUID")


@router.get("/internal/balance", response_model=BalanceResponse)
async def get_balance(
    account_id: uuid.UUID = Depends(_parse_account_id),
    session: AsyncSession = Depends(get_session),
) -> BalanceResponse:
    """Return the consumer balance for the given account."""
    balance_cents = await ledger.get_balance(session, account_id)
    return BalanceResponse(balance_cents=balance_cents)


@router.get("/internal/history", response_model=TransactionHistoryResponse)
async def get_transaction_history(
    account_id: uuid.UUID = Depends(_parse_account_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> TransactionHistoryResponse:
    """Return paginated transaction history for the given account."""
    entries, total = await ledger.get_transaction_history(
        session, account_id, limit=limit, offset=offset
    )

    transactions = [
        TransactionSummary(
            id=entry.id,
            entry_type=entry.entry_type,
            amount_cents=entry.amount_cents,
            description=entry.description,
            created_at=entry.created_at,
        )
        for entry in entries
    ]

    return TransactionHistoryResponse(transactions=transactions, total=total)
