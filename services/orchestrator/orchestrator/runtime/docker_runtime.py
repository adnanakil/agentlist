"""Docker-based agent execution runtime."""

from __future__ import annotations

import asyncio
import json
import time
from functools import partial

import docker
import docker.errors
import structlog

from orchestrator.runtime.base import ExecutionResult, RuntimeBase

log = structlog.get_logger()


class DockerRuntime(RuntimeBase):
    """Runs agent containers using the Docker SDK.

    All Docker SDK calls are synchronous, so they are dispatched to a
    thread executor via ``asyncio.get_event_loop().run_in_executor``.
    """

    def __init__(self) -> None:
        self._client: docker.DockerClient | None = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def execute(
        self,
        image_uri: str,
        input_data: dict,
        env_vars: dict,
        timeout_seconds: int,
        memory_limit_mb: int,
        cpu_limit: float,
    ) -> ExecutionResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                self._execute_sync,
                image_uri=image_uri,
                input_data=input_data,
                env_vars=env_vars,
                timeout_seconds=timeout_seconds,
                memory_limit_mb=memory_limit_mb,
                cpu_limit=cpu_limit,
            ),
        )

    # ------------------------------------------------------------------ #
    # Synchronous execution (runs in thread pool)
    # ------------------------------------------------------------------ #

    def _execute_sync(
        self,
        *,
        image_uri: str,
        input_data: dict,
        env_vars: dict,
        timeout_seconds: int,
        memory_limit_mb: int,
        cpu_limit: float,
    ) -> ExecutionResult:
        container = None
        start = time.monotonic()

        # Inject the agent input as an environment variable so the agent
        # process can read it from AGENT_INPUT.
        run_env = {**env_vars, "AGENT_INPUT": json.dumps(input_data)}

        try:
            container = self.client.containers.create(
                image=image_uri,
                command=["python", "-m", "agent"],
                environment=run_env,
                mem_limit=f"{memory_limit_mb}m",
                nano_cpus=int(cpu_limit * 1e9),
                security_opt=["no-new-privileges"],
                cap_drop=["ALL"],
                read_only=True,
                tmpfs={"/tmp": "size=100m"},
                network_disabled=True,
                detach=True,
            )

            container.start()

            # Wait for exit with timeout
            exit_info = container.wait(timeout=timeout_seconds)
            duration_ms = int((time.monotonic() - start) * 1000)

            exit_code = exit_info.get("StatusCode", -1)
            raw_logs = container.logs(stdout=True, stderr=True).decode(
                "utf-8", errors="replace"
            )

            if exit_code != 0:
                log.warning(
                    "agent.execution.failed",
                    image=image_uri,
                    exit_code=exit_code,
                    logs=raw_logs[:2000],
                )
                return ExecutionResult(
                    success=False,
                    error=f"Agent exited with code {exit_code}: {raw_logs[:2000]}",
                    duration_ms=duration_ms,
                )

            # Agent is expected to write a JSON object to stdout.
            stdout = container.logs(stdout=True, stderr=False).decode(
                "utf-8", errors="replace"
            )
            try:
                output = json.loads(stdout.strip())
            except (json.JSONDecodeError, ValueError):
                log.warning(
                    "agent.output.invalid_json",
                    image=image_uri,
                    stdout=stdout[:2000],
                )
                return ExecutionResult(
                    success=False,
                    error=f"Agent produced invalid JSON output: {stdout[:500]}",
                    duration_ms=duration_ms,
                )

            return ExecutionResult(
                success=True,
                output=output,
                duration_ms=duration_ms,
            )

        except docker.errors.ContainerError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.error("agent.container_error", image=image_uri, error=str(exc))
            return ExecutionResult(
                success=False,
                error=f"Container error: {exc}",
                duration_ms=duration_ms,
            )

        except (ConnectionError, docker.errors.APIError) as exc:
            # Timeout: the container.wait() raises ConnectionError or
            # ReadTimeout when the deadline is exceeded.
            duration_ms = int((time.monotonic() - start) * 1000)
            timed_out = duration_ms >= (timeout_seconds * 1000 - 500)

            if timed_out and container is not None:
                log.warning(
                    "agent.timeout",
                    image=image_uri,
                    timeout_seconds=timeout_seconds,
                )
                try:
                    container.kill()
                except docker.errors.APIError:
                    pass
                return ExecutionResult(
                    success=False,
                    error="timeout",
                    duration_ms=duration_ms,
                )

            log.error("agent.docker_api_error", image=image_uri, error=str(exc))
            return ExecutionResult(
                success=False,
                error=f"Docker API error: {exc}",
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.error(
                "agent.unexpected_error",
                image=image_uri,
                error=str(exc),
                exc_info=True,
            )
            return ExecutionResult(
                success=False,
                error=f"Unexpected error: {exc}",
                duration_ms=duration_ms,
            )

        finally:
            # Always attempt to remove the container.
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.APIError:
                    pass
