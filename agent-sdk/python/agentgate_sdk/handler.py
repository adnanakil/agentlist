"""Base handler for AgentGate agents.

Agent developers subclass AgentHandler and implement the `handle` method.
The runtime calls `run_agent()` which reads input from AGENT_INPUT env var,
invokes the handler, and prints JSON output to stdout.
"""

import json
import os
import sys
import traceback
from abc import ABC, abstractmethod
from typing import Any


class AgentHandler(ABC):
    """Base class for all AgentGate agents."""

    @abstractmethod
    def handle(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Process input and return output.

        Args:
            input_data: The input payload from the consumer.

        Returns:
            A dict that will be serialized as JSON and returned to the consumer.

        Raises:
            Exception: Any exception will be caught and reported as an agent error.
        """
        ...

    def get_credential(self, name: str) -> str:
        """Read a credential injected by the platform."""
        value = os.environ.get(f"AGENT_CRED_{name.upper()}")
        if value is None:
            raise ValueError(f"Credential '{name}' not found in environment")
        return value


def run_agent(handler: AgentHandler) -> None:
    """Entry point called by the container runtime.

    Reads AGENT_INPUT from env, calls handler.handle(), writes JSON to stdout.
    """
    try:
        raw_input = os.environ.get("AGENT_INPUT", "{}")
        input_data = json.loads(raw_input)
        result = handler.handle(input_data)
        output = {"success": True, "data": result}
    except Exception as e:
        output = {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

    json.dump(output, sys.stdout)
    sys.stdout.flush()


def run_local(handler: AgentHandler, input_data: dict[str, Any]) -> dict[str, Any]:
    """Test harness for local development. Runs handler directly without container."""
    os.environ["AGENT_INPUT"] = json.dumps(input_data)
    try:
        result = handler.handle(input_data)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
