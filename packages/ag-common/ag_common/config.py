from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://agentgate:agentgate@localhost:5432/agentgate"
    redis_url: str = "redis://localhost:6379/0"


class GatewayConfig(BaseConfig):
    registry_url: str = "http://localhost:8001"
    billing_url: str = "http://localhost:8002"
    orchestrator_url: str = "http://localhost:8003"
    rate_limit_per_minute: int = 100


class RegistryConfig(BaseConfig):
    openai_api_key: str = ""


class BillingConfig(BaseConfig):
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_success_url: str = "https://agentgate.com/billing/success"
    stripe_cancel_url: str = "https://agentgate.com/billing/cancel"


class OrchestratorConfig(BaseConfig):
    billing_url: str = "http://localhost:8002"
    agent_timeout_seconds: int = 300
    agent_memory_limit_mb: int = 512
    agent_cpu_limit: float = 1.0
    encryption_key: str = ""
