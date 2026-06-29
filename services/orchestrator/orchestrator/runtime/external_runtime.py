"""External runtime — proxies invocations to a developer-hosted endpoint."""

from __future__ import annotations

import time

import httpx
import structlog

from orchestrator.runtime.base import ExecutionResult, RuntimeBase

log = structlog.get_logger()


class ExternalRuntime(RuntimeBase):
    """Forwards agent invocations to a developer-provided HTTP endpoint.

    The endpoint receives a POST request with JSON body::

        {"input": {...}}

    And must return a JSON response::

        {"output": {...}}

    Or an error::

        {"error": "reason"}
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    async def execute(
        self,
        image_uri: str,
        input_data: dict,
        env_vars: dict,
        timeout_seconds: int,
        memory_limit_mb: int,
        cpu_limit: float,
        *,
        endpoint_url: str = "",
    ) -> ExecutionResult:
        if not endpoint_url:
            return ExecutionResult(
                success=False,
                error="No endpoint_url configured for external agent",
            )

        start = time.monotonic()

        try:
            resp = await self._client.post(
                endpoint_url,
                json={"input": input_data},
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException:
            elapsed = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                success=False,
                error="timeout",
                duration_ms=elapsed,
            )
        except httpx.HTTPError as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            log.error(
                "external.request_failed",
                endpoint_url=endpoint_url,
                error=str(exc),
            )
            return ExecutionResult(
                success=False,
                error=f"Failed to reach external endpoint: {exc}",
                duration_ms=elapsed,
            )

        elapsed = int((time.monotonic() - start) * 1000)

        if resp.status_code >= 400:
            return ExecutionResult(
                success=False,
                error=f"External endpoint returned {resp.status_code}: {resp.text[:500]}",
                duration_ms=elapsed,
            )

        try:
            data = resp.json()
        except Exception:
            return ExecutionResult(
                success=False,
                error="External endpoint returned invalid JSON",
                duration_ms=elapsed,
            )

        if "error" in data and data["error"]:
            return ExecutionResult(
                success=False,
                error=str(data["error"]),
                duration_ms=elapsed,
            )

        return ExecutionResult(
            success=True,
            output=data.get("output", data),
            duration_ms=elapsed,
        )
