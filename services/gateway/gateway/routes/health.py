"""Health-check endpoint."""

from fastapi import APIRouter

from ag_common.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Shallow health check — confirms the gateway process is alive."""
    return HealthResponse(status="ok", service="gateway", version="0.1.0")
