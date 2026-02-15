"""Agent discovery route — proxies to the registry service."""

import structlog
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from ag_common.errors import AgentGateError
from ag_common.models import AuthenticatedAccount, DiscoverRequest, DiscoverResponse

from gateway.config import settings
from gateway.deps import get_http_client
from gateway.middleware.rate_limit import check_rate_limit

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["discovery"])


@router.post("/discover", response_model=DiscoverResponse)
async def discover(
    body: DiscoverRequest,
    account: AuthenticatedAccount = Depends(check_rate_limit),
    http: AsyncClient = Depends(get_http_client),
) -> DiscoverResponse:
    """Search the agent registry.

    Forwards the request to the registry service's internal endpoint and
    returns the matched agents.
    """
    logger.info(
        "discover_request",
        account_id=str(account.account_id),
        query=body.query,
        category=body.category,
    )

    url = f"{settings.registry_url}/internal/discover"

    response = await http.post(
        url,
        json=body.model_dump(mode="json"),
        headers={"X-Account-ID": str(account.account_id)},
    )

    if response.status_code != 200:
        logger.error(
            "registry_error",
            status=response.status_code,
            body=response.text[:500],
        )
        raise AgentGateError(
            f"Registry service returned {response.status_code}",
            details={"upstream_status": response.status_code},
        )

    return DiscoverResponse.model_validate(response.json())
