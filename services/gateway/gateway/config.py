"""Gateway configuration — re-exports GatewayConfig from ag_common."""

from ag_common.config import GatewayConfig

__all__ = ["GatewayConfig"]

settings = GatewayConfig()
