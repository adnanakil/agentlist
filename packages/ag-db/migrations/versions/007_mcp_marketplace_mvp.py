"""Add MCP marketplace MVP tables and listing metadata.

Revision ID: 007
Revises: 006
Create Date: 2026-05-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("runtime_kind", sa.String(40), nullable=False, server_default="python"),
    )
    op.add_column("agents", sa.Column("runtime_version", sa.String(40), nullable=True))
    op.add_column("agents", sa.Column("entry_point", sa.String(255), nullable=True))
    op.add_column("agents", sa.Column("tool_schema", JSONB, nullable=False, server_default="[]"))
    op.add_column(
        "agents",
        sa.Column("pricing_model", sa.String(40), nullable=False, server_default="per_call"),
    )
    op.add_column(
        "agents",
        sa.Column("pricing_config", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "agents",
        sa.Column("install_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("agents", sa.Column("rating_avg", sa.Float(), nullable=True))
    op.add_column(
        "agents",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agents_pricing_model", "agents", ["pricing_model"])

    op.create_table(
        "mcp_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema", JSONB, nullable=False, server_default="{}"),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "name", name="uq_mcp_tool_agent_name"),
    )
    op.create_index("ix_mcp_tools_agent", "mcp_tools", ["agent_id"])

    op.create_table(
        "mcp_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("current_period_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "agent_id", name="uq_mcp_subscription_account_agent"),
    )
    op.create_index("ix_mcp_subscriptions_account", "mcp_subscriptions", ["account_id"])
    op.create_index("ix_mcp_subscriptions_status", "mcp_subscriptions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mcp_subscriptions_status", table_name="mcp_subscriptions")
    op.drop_index("ix_mcp_subscriptions_account", table_name="mcp_subscriptions")
    op.drop_table("mcp_subscriptions")

    op.drop_index("ix_mcp_tools_agent", table_name="mcp_tools")
    op.drop_table("mcp_tools")

    op.drop_index("ix_agents_pricing_model", table_name="agents")
    op.drop_column("agents", "rating_count")
    op.drop_column("agents", "rating_avg")
    op.drop_column("agents", "install_count")
    op.drop_column("agents", "pricing_config")
    op.drop_column("agents", "pricing_model")
    op.drop_column("agents", "tool_schema")
    op.drop_column("agents", "entry_point")
    op.drop_column("agents", "runtime_version")
    op.drop_column("agents", "runtime_kind")
