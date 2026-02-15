"""Billing routes — balance, history, and deposits."""

import structlog
from fastapi import APIRouter, Depends, Query
from httpx import AsyncClient

from ag_common.errors import AgentGateError
from ag_common.models import (
    AuthenticatedAccount,
    BalanceResponse,
    DepositRequest,
    DepositResponse,
    TransactionHistoryResponse,
)

from gateway.config import settings
from gateway.deps import get_http_client
from gateway.middleware.rate_limit import check_rate_limit

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["billing"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _billing_headers(account: AuthenticatedAccount) -> dict[str, str]:
    """Standard headers forwarded to the billing service."""
    return {"X-Account-ID": str(account.account_id)}


async def _forward_get(
    http: AsyncClient,
    path: str,
    account: AuthenticatedAccount,
    params: dict | None = None,
) -> dict:
    """Issue a GET to the billing service and return the JSON body."""
    url = f"{settings.billing_url}{path}"
    response = await http.get(url, headers=_billing_headers(account), params=params)

    if response.status_code != 200:
        logger.error("billing_get_error", status=response.status_code, path=path)
        raise AgentGateError(
            f"Billing service returned {response.status_code}",
            details={"upstream_status": response.status_code},
        )

    return response.json()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    account: AuthenticatedAccount = Depends(check_rate_limit),
    http: AsyncClient = Depends(get_http_client),
) -> BalanceResponse:
    """Return the current credit balance for the authenticated account."""
    logger.info("balance_request", account_id=str(account.account_id))
    data = await _forward_get(http, "/internal/balance", account)
    return BalanceResponse.model_validate(data)


@router.get("/history", response_model=TransactionHistoryResponse)
async def get_history(
    account: AuthenticatedAccount = Depends(check_rate_limit),
    http: AsyncClient = Depends(get_http_client),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> TransactionHistoryResponse:
    """Return transaction history for the authenticated account."""
    logger.info("history_request", account_id=str(account.account_id), limit=limit, offset=offset)
    data = await _forward_get(
        http,
        "/internal/history",
        account,
        params={"limit": limit, "offset": offset},
    )
    return TransactionHistoryResponse.model_validate(data)


@router.post("/deposit", response_model=DepositResponse)
async def deposit(
    body: DepositRequest,
    account: AuthenticatedAccount = Depends(check_rate_limit),
    http: AsyncClient = Depends(get_http_client),
) -> DepositResponse:
    """Create a Stripe checkout session to add funds."""
    logger.info(
        "deposit_request",
        account_id=str(account.account_id),
        amount_cents=body.amount_cents,
    )

    url = f"{settings.billing_url}/internal/deposit"
    response = await http.post(
        url,
        json=body.model_dump(mode="json"),
        headers=_billing_headers(account),
    )

    if response.status_code != 200:
        logger.error("billing_deposit_error", status=response.status_code)
        raise AgentGateError(
            f"Billing service returned {response.status_code}",
            details={"upstream_status": response.status_code},
        )

    return DepositResponse.model_validate(response.json())
