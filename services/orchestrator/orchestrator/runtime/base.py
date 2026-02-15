"""Abstract runtime interface for agent execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    success: bool
    output: dict | None = None
    error: str | None = None
    duration_ms: int = 0


class RuntimeBase(ABC):
    @abstractmethod
    async def execute(
        self,
        image_uri: str,
        input_data: dict,
        env_vars: dict,
        timeout_seconds: int,
        memory_limit_mb: int,
        cpu_limit: float,
    ) -> ExecutionResult:
        ...
