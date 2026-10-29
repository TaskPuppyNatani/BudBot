"""Add expiring, revocable business team invitations.

Revision ID: 0009_m9b_business_invitations
Revises: 0008_m9b_tenant_ai
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_m9b_business_invitations"
down_revision: str | None = "0008_m9b_tenant_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_invitations",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_business_invitations_token_digest"),
    )
    op.create_index("ix_business_invitations_business_id", "business_invitations", ["business_id"])
    op.create_index("ix_business_invitations_created_by_user_id", "business_invitations", ["created_by_user_id"])
    op.create_index("ix_business_invitations_expires_at", "business_invitations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_business_invitations_expires_at", table_name="business_invitations")
    op.drop_index("ix_business_invitations_created_by_user_id", table_name="business_invitations")
    op.drop_index("ix_business_invitations_business_id", table_name="business_invitations")
    op.drop_table("business_invitations")
