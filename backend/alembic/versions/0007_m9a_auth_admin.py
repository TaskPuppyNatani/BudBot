"""Add first-party administrative authentication, sessions, and audit state.

Revision ID: 0007_m9a_auth_admin
Revises: 0006_m6_provider_neutral_catalog
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_m9a_auth_admin"
down_revision: str | None = "0006_m6_provider_neutral_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("password_hash", sa.String(255)))

    op.create_table(
        "admin_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_admin_sessions_token_digest"),
    )
    op.create_index("ix_admin_sessions_user_id", "admin_sessions", ["user_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    op.create_table(
        "auth_setup_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_auth_setup_state_singleton"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO auth_setup_state (id, initialized_at, owner_user_id) "
            "VALUES (1, NULL, NULL)"
        )
    )

    op.create_table(
        "admin_login_rate_limits",
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key_digest"),
    )

    op.create_table(
        "audit_events",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_business_id", "audit_events", ["business_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_business_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("admin_login_rate_limits")
    op.drop_table("auth_setup_state")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_user_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_column("user_accounts", "password_hash")
