"""Initial schema.

Revision ID: 001
Revises: None
Create Date: 2026-02-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    account_role = sa.Enum("consumer", "developer", "admin", name="account_role")
    agent_runtime = sa.Enum("python", name="agent_runtime")
    agent_status = sa.Enum("draft", "review", "active", "suspended", name="agent_status")
    ledger_account_type = sa.Enum(
        "consumer_balance", "developer_earnings", "platform_revenue", "held_funds",
        name="ledger_account_type",
    )
    hold_status = sa.Enum("active", "settled", "released", name="hold_status")
    invocation_status = sa.Enum(
        "pending", "running", "completed", "failed", "timeout", "error",
        name="invocation_status",
    )

    # accounts
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", account_role, nullable=False, server_default="consumer"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("daily_spending_cap_cents", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # categories
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # agents
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "developer_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column(
            "category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True
        ),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default="0.1.0"),
        sa.Column("runtime", agent_runtime, nullable=False, server_default="python"),
        sa.Column("status", agent_status, nullable=False, server_default="draft"),
        sa.Column("price_per_call_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_schema", JSONB, nullable=False, server_default="{}"),
        sa.Column("manifest", JSONB, nullable=False, server_default="{}"),
        sa.Column("description_embedding", JSONB, nullable=True),
        sa.Column("tags", JSONB, nullable=False, server_default="[]"),
        sa.Column("image_uri", sa.String(500), nullable=True),
        sa.Column("total_invocations", sa.Integer, server_default="0"),
        sa.Column("success_rate", sa.Float, server_default="0.0"),
        sa.Column("avg_latency_ms", sa.Float, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_agents_slug", "agents", ["slug"])

    # agent_credentials
    op.create_table(
        "agent_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("credential_name", sa.String(100), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        sa.Column("encryption_key_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "credential_name", name="uq_agent_credential"),
    )

    # ledger_accounts
    op.create_table(
        "ledger_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("account_type", ledger_account_type, nullable=False),
        sa.Column("balance_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "account_type", name="uq_ledger_account"),
    )

    # ledger_entries
    op.create_table(
        "ledger_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column(
            "debit_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "credit_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("invocation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ledger_entries_invocation", "ledger_entries", ["invocation_id"])
    op.create_index("ix_ledger_entries_stripe", "ledger_entries", ["stripe_payment_intent_id"])

    # billing_holds
    op.create_table(
        "billing_holds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "consumer_ledger_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "held_funds_ledger_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column("invocation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("status", hold_status, nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_billing_holds_status", "billing_holds", ["status"])
    op.create_index("ix_billing_holds_expires", "billing_holds", ["expires_at"])

    # invocations
    op.create_table(
        "invocations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "consumer_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column(
            "agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("status", invocation_status, nullable=False, server_default="pending"),
        sa.Column("input", JSONB, nullable=False, server_default="{}"),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "hold_id", UUID(as_uuid=True), sa.ForeignKey("billing_holds.id"), nullable=True
        ),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invocations_consumer", "invocations", ["consumer_id"])
    op.create_index("ix_invocations_agent", "invocations", ["agent_id"])
    op.create_index("ix_invocations_status", "invocations", ["status"])

    # stripe_events (idempotency)
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_table("invocations")
    op.drop_table("billing_holds")
    op.drop_table("ledger_entries")
    op.drop_table("ledger_accounts")
    op.drop_table("agent_credentials")
    op.drop_table("agents")
    op.drop_table("categories")
    op.drop_table("api_keys")
    op.drop_table("accounts")

    op.execute("DROP TYPE IF EXISTS invocation_status")
    op.execute("DROP TYPE IF EXISTS hold_status")
    op.execute("DROP TYPE IF EXISTS ledger_account_type")
    op.execute("DROP TYPE IF EXISTS agent_status")
    op.execute("DROP TYPE IF EXISTS agent_runtime")
    op.execute("DROP TYPE IF EXISTS account_role")
