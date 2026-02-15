"""Internal routes for hold management (place, settle, release)."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session

from billing.services import holds

log = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PlaceHoldRequest(BaseModel):
    consumer_account_id: uuid.UUID
    amount_cents: int = Field(ge=1)
    invocation_id: uuid.UUID | None = None


class HoldResponse(BaseModel):
    hold_id: uuid.UUID
    status: str
    amount_cents: int


class SettleHoldRequest(BaseModel):
    developer_account_id: uuid.UUID


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/internal/holds", response_model=HoldResponse)
async def place_hold(
    body: PlaceHoldRequest,
    session: AsyncSession = Depends(get_session),
) -> HoldResponse:
    """Place a billing hold for an invocation."""
    hold = await holds.place_hold(
        session=session,
        consumer_account_id=body.consumer_account_id,
        amount_cents=body.amount_cents,
        invocation_id=body.invocation_id,
    )
    await session.commit()

    return HoldResponse(
        hold_id=hold.id,
        status=hold.status,
        amount_cents=hold.amount_cents,
    )


@router.post("/internal/holds/{hold_id}/settle", response_model=HoldResponse)
async def settle_hold(
    hold_id: uuid.UUID,
    body: SettleHoldRequest,
    session: AsyncSession = Depends(get_session),
) -> HoldResponse:
    """Settle a hold after a successful invocation."""
    hold = await holds.settle_hold(
        session=session,
        hold_id=hold_id,
        developer_account_id=body.developer_account_id,
    )
    await session.commit()

    return HoldResponse(
        hold_id=hold.id,
        status=hold.status,
        amount_cents=hold.amount_cents,
    )


@router.post("/internal/holds/{hold_id}/release", response_model=HoldResponse)
async def release_hold(
    hold_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> HoldResponse:
    """Release a hold — refund funds to the consumer."""
    hold = await holds.release_hold(
        session=session,
        hold_id=hold_id,
    )
    await session.commit()

    return HoldResponse(
        hold_id=hold.id,
        status=hold.status,
        amount_cents=hold.amount_cents,
    )
