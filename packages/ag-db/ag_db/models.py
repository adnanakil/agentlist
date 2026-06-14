"""SQLAlchemy models for AgentGate."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


# --- Accounts & Auth ---


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("consumer", "developer", "admin", name="account_role"),
        nullable=False,
        default="consumer",
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_spending_cap_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="account")
    ledger_accounts: Mapped[list["LedgerAccount"]] = relationship(back_populates="account")
    consumer_credentials: Mapped[list["ConsumerCredential"]] = relationship(back_populates="account")
    mcp_subscriptions: Mapped[list["McpSubscription"]] = relationship(back_populates="account")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="api_keys")

    __table_args__ = (Index("ix_api_keys_key_hash", "key_hash"),)


# --- Categories & Agents ---


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agents: Mapped[list["Agent"]] = relationship(back_populates="category")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    developer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")
    runtime: Mapped[str] = mapped_column(
        Enum("python", name="agent_runtime"),
        nullable=False,
        default="python",
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "review", "active", "suspended", name="agent_status"),
        nullable=False,
        default="draft",
    )
    price_per_call_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description_embedding = mapped_column(JSONB, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    image_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    required_consumer_credentials: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    runtime_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="python")
    runtime_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entry_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_schema: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    pricing_model: Mapped[str] = mapped_column(String(40), nullable=False, default="per_call")
    pricing_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    install_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Stats
    total_invocations: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    category: Mapped["Category | None"] = relationship(back_populates="agents")
    credentials: Mapped[list["AgentCredential"]] = relationship(back_populates="agent")
    mcp_tools: Mapped[list["McpTool"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    mcp_subscriptions: Mapped[list["McpSubscription"]] = relationship(back_populates="agent")

    __table_args__ = (
        Index("ix_agents_status", "status"),
        Index("ix_agents_slug", "slug"),
        Index("ix_agents_pricing_model", "pricing_model"),
    )


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    credential_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="credentials")

    __table_args__ = (
        UniqueConstraint("agent_id", "credential_name", name="uq_agent_credential"),
    )


class ConsumerCredential(Base):
    __tablename__ = "consumer_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="consumer_credentials")

    __table_args__ = (
        UniqueConstraint("account_id", "service_name", name="uq_consumer_credential"),
    )


class McpTool(Base):
    __tablename__ = "mcp_tools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="mcp_tools")

    __table_args__ = (
        UniqueConstraint("agent_id", "name", name="uq_mcp_tool_agent_name"),
        Index("ix_mcp_tools_agent", "agent_id"),
    )


class McpSubscription(Base):
    __tablename__ = "mcp_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    current_period_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    account: Mapped["Account"] = relationship(back_populates="mcp_subscriptions")
    agent: Mapped["Agent"] = relationship(back_populates="mcp_subscriptions")

    __table_args__ = (
        UniqueConstraint("account_id", "agent_id", name="uq_mcp_subscription_account_agent"),
        Index("ix_mcp_subscriptions_account", "account_id"),
        Index("ix_mcp_subscriptions_status", "status"),
    )


# --- Billing ---


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    account_type: Mapped[str] = mapped_column(
        Enum(
            "consumer_balance",
            "developer_earnings",
            "platform_revenue",
            "held_funds",
            name="ledger_account_type",
        ),
        nullable=False,
    )
    balance_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    account: Mapped["Account"] = relationship(back_populates="ledger_accounts")

    __table_args__ = (
        UniqueConstraint("account_id", "account_type", name="uq_ledger_account"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    debit_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    credit_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_ledger_entries_invocation", "invocation_id"),
        Index("ix_ledger_entries_stripe", "stripe_payment_intent_id"),
    )


class BillingHold(Base):
    __tablename__ = "billing_holds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    consumer_ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    held_funds_ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "settled", "released", name="hold_status"),
        nullable=False,
        default="active",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_billing_holds_status", "status"),
        Index("ix_billing_holds_expires", "expires_at"),
    )


# --- Invocations ---


class Invocation(Base):
    __tablename__ = "invocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    consumer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "running", "completed", "failed", "timeout", "error",
            name="invocation_status",
        ),
        nullable=False,
        default="pending",
    )
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_holds.id"), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_invocations_consumer", "consumer_id"),
        Index("ix_invocations_agent", "agent_id"),
        Index("ix_invocations_status", "status"),
    )


# --- Stripe Events (idempotency) ---


class AgentSubscription(Base):
    __tablename__ = "agent_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending_provision", "active", "suspended", "cancelled",
            name="subscription_status",
        ),
        nullable=False,
    )
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("phone", "agent_slug", name="uq_subscription_phone_agent"),
        Index("ix_agent_subscriptions_status", "status"),
        Index("ix_agent_subscriptions_phone", "phone"),
    )


# --- Stripe Events (idempotency) ---


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- HAL Orchestrator ---
# NOTE: `phone` columns hold the SILO KEY, not just phone numbers: a normalized
# E.164 phone or lowercased email for 1:1 chats, or the iMessage group chat id
# (e.g. "chat63837193722342854…") for group chats. Hence String(255).


class HalConversation(Base):
    __tablename__ = "hal_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    history: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Rolling long-horizon summary of older context (maintained by the curator).
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # message_count at the last summary refresh, so the summarizer only re-runs
    # when there's been meaningful new activity.
    summarized_at_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_hal_conversations_phone", "phone"),)


class HalUserProfile(Base):
    __tablename__ = "hal_user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    google_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # conversation.message_count at the last background profile enrichment, so the
    # enricher daemon only re-runs after enough new activity (mirrors the
    # summarizer's summarized_at_count).
    enriched_at_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_hal_user_profiles_phone", "phone"),)


class HalUserMemory(Base):
    __tablename__ = "hal_user_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 768-dim Gemini embedding for semantic recall (app-side cosine; no pgvector).
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_user_memories_phone", "phone"),)


class HalReminder(Base):
    __tablename__ = "hal_reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recurrence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    group_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_hal_reminders_phone", "phone"),
        Index("ix_hal_reminders_due_at", "due_at"),
    )


class HalUserSkill(Base):
    """User-authored skills. Bundled skills live on the filesystem in the
    hal_orchestrator package and are read-only — this table is just the
    user-mutable layer. User entries override bundled entries of the same name.

    Owned by a silo (`phone`): a user's skills are private to them; a group
    chat's skills are private to that group. Names are unique per silo."""

    __tablename__ = "hal_user_skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    inputs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Sibling files keyed by relative path under references/, templates/, scripts/.
    # e.g. {"references/format.md": "Bullets must be one line each..."}
    files: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_hal_user_skills_name", "name"),
        Index("ix_hal_user_skills_phone", "phone"),
        UniqueConstraint("phone", "name", name="uq_hal_user_skills_phone_name"),
    )


class HalGoogleAccount(Base):
    """Per-silo Google OAuth tokens, encrypted at rest (Fernet).

    Keyed by silo `phone` like all HAL state: each user connects THEIR OWN
    Google account in their 1:1 chat. Group silos never hold one (enforced in
    the tools), so no member's email/calendar is reachable from a group."""

    __tablename__ = "hal_google_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Fernet-encrypted token strings (never store plaintext OAuth tokens).
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_hal_google_accounts_phone", "phone"),)


class HalWatchedGroup(Base):
    """Group chats HAL watches ambiently — it receives EVERY message (not just
    @Hal mentions) so it can chime in proactively, but is prompted to stay
    silent unless addressed or genuinely useful. Decoupled from trips: a group
    can be watched without any trip being planned."""

    __tablename__ = "hal_watched_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    chat_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_watched_groups_chat_id", "chat_id"),)


class HalMessage(Base):
    """Append-only message archive (per silo) for cross-session full-text +
    temporal recall. The rolling hal_conversations.history is trimmed to a
    window; this keeps every text turn durably so HAL can answer "what did we
    talk about last Tuesday / about X". Postgres FTS (GIN tsvector index added
    in the migration) powers keyword search; created_at powers time scoping."""

    __tablename__ = "hal_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)  # silo
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_messages_phone_created", "phone", "created_at"),)


class HalCronJob(Base):
    """Agentic scheduled tasks: at the scheduled time HAL runs a full agent turn
    on `prompt` in the silo's context and delivers the result. Distinct from
    HalReminder (which just re-sends static text)."""

    __tablename__ = "hal_cron_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)  # silo / delivery target
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # once | daily | weekdays | weekly | monthly
    recurrence: Mapped[str] = mapped_column(String(16), nullable=False, default="once")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_cron_jobs_due", "active", "next_run_at"),)


class HalSkillTrajectory(Base):
    """A completed multi-tool task captured for possible distillation into a
    reusable skill (the skill-synthesizer daemon decides). Per silo: a learned
    skill belongs to the user/group it came from."""

    __tablename__ = "hal_skill_trajectories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)  # silo
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    outcome: Mapped[str] = mapped_column(Text, nullable=False, default="")
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_skill_trajectories_processed", "processed"),)


class HalFrictionEvent(Base):
    """Signals that feed the nightly reflection's feature proposals: a stubbed
    tool was requested (unmet demand), a turn hit the iteration cap (HAL got
    stuck), or a tool errored. Per silo, but used in aggregate."""

    __tablename__ = "hal_friction_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # stub_tool|stuck|tool_error
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_friction_created", "created_at"),)


class HalReflection(Base):
    """A nightly self-improvement report: skills auto-created + ranked feature
    proposals. Saved for history and texted to the admin."""

    __tablename__ = "hal_reflections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_reflections_created", "created_at"),)


class HalWatch(Base):
    """Notify-when-condition watcher. A background checker re-polls `condition`
    on a cheap model and, the first time it's true, delivers `notify` once and
    deactivates. Silent until then. Distinct from HalCronJob (clock schedule)
    and HalReminder (static text)."""

    __tablename__ = "hal_watches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)        # silo / delivery target
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    check_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    notify: Mapped[str] = mapped_column(Text, nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    poll_every_seconds: Mapped[int] = mapped_column(Integer, default=150)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_polls: Mapped[int] = mapped_column(Integer, default=60)
    polls_done: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_fails: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_watches_due", "active", "next_run_at"),)


class HalCuratorState(Base):
    """Singleton row tracking when the curator last ran."""

    __tablename__ = "hal_curator_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_summary: Mapped[str] = mapped_column(Text, default="")
    last_actions_count: Mapped[int] = mapped_column(Integer, default=0)
    last_applied_count: Mapped[int] = mapped_column(Integer, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HalTrip(Base):
    __tablename__ = "hal_trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="collecting")
    created_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    participants: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    locked_dates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    votes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    winner: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_hal_trips_chat_id", "chat_id"),
        Index("ix_hal_trips_status", "status"),
    )


class HalFamily(Base):
    """A family unit sharing one baby's event log. The ONE deliberate exception
    to silo isolation: the baby is a shared entity, so the parents' 1:1 silos
    and the family group chat silo are all members and read/write the same
    events. Membership is explicit (seed/admin or baby setup) — nothing else
    crosses silos."""

    __tablename__ = "hal_families"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    baby_name: Mapped[str] = mapped_column(String(100), nullable=False)
    baby_birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/New_York")
    # auto_reminders, auto_wind_down, auto_feed_prep, nap_cap_minutes,
    # routines: [{after, offset_min, text}], ...
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Watcher bookkeeping (e.g. last nap-cap nudge event id) — not user config.
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HalFamilyMember(Base):
    """Maps a silo (1:1 phone or group chat id) to its family. One family per
    silo — the baby tool resolves the family from ctx.phone."""

    __tablename__ = "hal_family_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hal_families.id", ondelete="CASCADE"), nullable=False
    )
    silo: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="parent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_family_members_family", "family_id"),)


class HalTurn(Base):
    """One agent turn, captured for the nightly growth loop (GROWTH.md).
    Unlike HalSkillTrajectory (≥5-tool successes only), EVERY turn lands here —
    including model failures and quiet-sentinel turns — so failures are visible.
    Content is private (data plane); the nightly grader reads it one silo at a
    time and only de-identified verdicts aggregate globally."""

    __tablename__ = "hal_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)  # silo
    sender_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ok")
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grade_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_hal_turns_ungraded", "graded_at", "created_at"),
        Index("ix_hal_turns_phone_created", "phone", "created_at"),
    )


class HalPlaybookEntry(Base):
    """A self-authored operating note injected into the system prompt for ALL
    users (global learning plane). Additive guidance only — hard rules stay
    code-owned. Each entry carries a falsifiable hypothesis (the failure it
    should eliminate) that the nightly verifier re-checks."""

    __tablename__ = "hal_playbook"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    origin_reflection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    clean_nights: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_nights: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_hal_playbook_status", "status"),)


class HalFeatureRequest(Base):
    """Persistent, deduped feature backlog (global learning plane). Evidence
    accumulates across nights; admin is pinged on new items or threshold
    crossings; high-priority items get a build spec drafted."""

    __tablename__ = "hal_feature_backlog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sketch: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spec: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_hal_feature_backlog_status", "status"),)


class HalBabyEvent(Base):
    """One logged baby event. Structured replacement for the free-text memory
    lines ("Bazzy fed 9:47am") — powers analytics, forecasts, and digests."""

    __tablename__ = "hal_baby_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hal_families.id", ondelete="CASCADE"), nullable=False
    )
    # feed | nap_start | wake | bedtime | tummy_time | diaper | note
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    silo: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_baby_events_family_at", "family_id", "event_at"),)


class HalGroupObservation(Base):
    """One-way valve from the group plane to a member's personal silo.

    Written ONLY by the group-side enricher (facts about a member, sourced
    from a group conversation they participated in); read ONLY by that
    member's 1:1 context. The group agent never reads this table, and nothing
    here ever flows back into a group — so personal HAL learns what's
    happening to its user in groups without the group gaining any access to
    personal state."""

    __tablename__ = "hal_group_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    member_phone: Mapped[str] = mapped_column(String(255), nullable=False)
    group_silo: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_hal_group_obs_member_created", "member_phone", "created_at"),
    )
