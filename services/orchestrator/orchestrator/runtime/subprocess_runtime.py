"""Subprocess-based agent execution runtime.

Runs agent code as a Python subprocess instead of inside a Docker container.
Designed for Railway and other environments where Docker-in-Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import structlog

from orchestrator.runtime.base import ExecutionResult, RuntimeBase

log = structlog.get_logger()

# Agents are shipped with the orchestrator image under /app/agents/
AGENTS_DIR = Path("/app/agents")


class SubprocessRuntime(RuntimeBase):
    """Runs agents as Python subprocesses."""

    def __init__(self, agents_dir: Path | None = None) -> None:
        self.agents_dir = agents_dir or AGENTS_DIR
        # Also check local dev path
        if not self.agents_dir.exists():
            local = Path(__file__).resolve().parents[4] / "agents"
            if local.exists():
                self.agents_dir = local

    async def execute(
        self,
        image_uri: str,
        input_data: dict,
        env_vars: dict,
        timeout_seconds: int,
        memory_limit_mb: int,
        cpu_limit: float,
        *,
        agent_code: str | None = None,
    ) -> ExecutionResult:
        start = time.monotonic()

        # Extract agent slug from image_uri (e.g. "agentgate-agent-echo:latest" -> "echo")
        slug = image_uri.split("agent-")[-1].split(":")[0] if "agent-" in image_uri else image_uri

        # Find the agent directory (curated agents baked into the image)
        agent_dir = self.agents_dir / slug
        tmp_dir: tempfile.TemporaryDirectory | None = None

        if agent_dir.exists():
            entrypoint = agent_dir / "agent.py"
            if not entrypoint.exists():
                return ExecutionResult(
                    success=False,
                    error=f"Agent entrypoint not found: {entrypoint}",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
        elif agent_code:
            # Web-submitted hosted agent — write code to a temp directory
            tmp_dir = tempfile.TemporaryDirectory(prefix=f"agent-{slug}-")
            agent_dir = Path(tmp_dir.name)
            entrypoint = agent_dir / "agent.py"
            entrypoint.write_text(agent_code)
            log.info("agent.using_inline_code", slug=slug)
        else:
            return ExecutionResult(
                success=False,
                error=f"Agent directory not found: {agent_dir}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        # Build environment
        import os
        run_env = {**os.environ, **env_vars, "AGENT_INPUT": json.dumps(input_data)}

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", str(entrypoint),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=run_env,
                cwd=str(agent_dir),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                duration_ms = int((time.monotonic() - start) * 1000)
                log.warning("agent.timeout", slug=slug, timeout_seconds=timeout_seconds)
                return ExecutionResult(
                    success=False,
                    error="timeout",
                    duration_ms=duration_ms,
                )

            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                log.warning(
                    "agent.execution.failed",
                    slug=slug,
                    exit_code=proc.returncode,
                    stderr=stderr[:2000],
                )
                return ExecutionResult(
                    success=False,
                    error=f"Agent exited with code {proc.returncode}: {stderr[:2000]}",
                    duration_ms=duration_ms,
                )

            # Parse JSON output from stdout
            try:
                output = json.loads(stdout.strip())
            except (json.JSONDecodeError, ValueError):
                log.warning("agent.output.invalid_json", slug=slug, stdout=stdout[:2000])
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

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.error("agent.unexpected_error", slug=slug, error=str(exc), exc_info=True)
            return ExecutionResult(
                success=False,
                error=f"Unexpected error: {exc}",
                duration_ms=duration_ms,
            )
        finally:
            if tmp_dir is not None:
                tmp_dir.cleanup()
