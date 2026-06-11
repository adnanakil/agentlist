"""Shared Pydantic models for request/response schemas."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# --- Enums ---


class AccountRole(str, Enum):
    consumer = "consumer"
    developer = "developer"
    admin = "admin"


class AgentStatus(str, Enum):
    draft = "draft"
    review = "review"
    active = "active"
    suspended = "suspended"


class AgentRuntime(str, Enum):
    python = "python"


class InvocationStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    error = "error"


class HoldStatus(str, Enum):
    active = "active"
    settled = "settled"
    released = "released"


class LedgerAccountType(str, Enum):
    consumer_balance = "consumer_balance"
    developer_earnings = "developer_earnings"
    platform_revenue = "platform_revenue"
    held_funds = "held_funds"


# --- Auth ---


class CreateAccountRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: AccountRole = AccountRole.consumer


class CreateAccountResponse(BaseModel):
    account_id: UUID
    email: str
    role: AccountRole
    api_key: str  # only returned once at creation


class AuthenticatedAccount(BaseModel):
    account_id: UUID
    email: str
    role: AccountRole


# --- Agents ---


class AgentSummary(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category: str
    price_per_call_cents: int
    tags: list[str]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    required_consumer_credentials: list[str] = Field(default_factory=list)
    total_invocations: int
    success_rate: float
    avg_latency_ms: float
    score: float | None = None


class AgentDetail(AgentSummary):
    version: str
    runtime: AgentRuntime
    created_at: datetime


# --- Discovery ---


class DiscoverRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    category: str | None = None
    max_price_cents: int | None = None
    limit: int = Field(default=10, ge=1, le=50)


class DiscoverResponse(BaseModel):
    agents: list[AgentSummary]
    total: int


# --- Invocation ---


class InvokeRequest(BaseModel):
    agent_id: UUID | None = None
    agent_slug: str | None = None
    input: dict[str, Any]


class InvokeResponse(BaseModel):
    invocation_id: UUID
    status: InvocationStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    price_cents: int | None = None


# --- Billing ---


class BalanceResponse(BaseModel):
    balance_cents: int
    currency: str = "usd"


class DepositRequest(BaseModel):
    amount_cents: int = Field(ge=100, le=1_000_000)  # $1 - $10,000


class DepositResponse(BaseModel):
    checkout_url: str
    session_id: str


class TransactionSummary(BaseModel):
    id: UUID
    entry_type: str
    amount_cents: int
    description: str
    created_at: datetime


class TransactionHistoryResponse(BaseModel):
    transactions: list[TransactionSummary]
    total: int


# --- Health ---


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str = "0.1.0"
