"""Agent invocation route — proxies to the orchestrator service."""

import structlog
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from ag_common.errors import AgentGateError
from ag_common.models import AuthenticatedAccount, InvokeRequest, InvokeResponse

from gateway.config import settings
from gateway.deps import get_http_client
from gateway.middleware.rate_limit import check_rate_limit

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["invocation"])


@router.post("/invoke", response_model=InvokeResponse)
async def invoke(
    body: InvokeRequest,
    account: AuthenticatedAccount = Depends(check_rate_limit),
    http: AsyncClient = Depends(get_http_client),
) -> InvokeResponse:
    """Invoke an agent.

    Forwards the request to the orchestrator service, which handles billing
    holds, sandbox execution, and settlement.
    """
    logger.info(
        "invoke_request",
        account_id=str(account.account_id),
        agent_id=str(body.agent_id) if body.agent_id else None,
        agent_slug=body.agent_slug,
    )

    url = f"{settings.orchestrator_url}/internal/invoke"

    response = await http.post(
        url,
        json=body.model_dump(mode="json"),
        headers={"X-Account-ID": str(account.account_id)},
        timeout=120.0,  # invocations can be long-running (research agents may need 10+ iterations)
    )

    if response.status_code != 200:
        logger.error(
            "orchestrator_error",
            status=response.status_code,
            body=response.text[:500],
        )
        raise AgentGateError(
            f"Orchestrator service returned {response.status_code}",
            details={"upstream_status": response.status_code},
        )

    return InvokeResponse.model_validate(response.json())
