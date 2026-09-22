"""Add M3 customer sessions and explicit compliance-profile configuration.

Revision ID: 0003_m3_sessions_compliance
Revises: 0002_m2_tenant_domain
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_m3_sessions_compliance"
down_revision: str | None = "0002_m2_tenant_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # Server defaults make the backfill safe for existing M2 businesses. The
    # application registry remains the authority for whether the values are
    # known and for the active profile version.
    op.add_column(
        "businesses",
        sa.Column(
            "compliance_profile_id",
            sa.String(length=100),
            server_default="general_retail",
            nullable=False,
        ),
    )
    op.add_column(
        "businesses",
        sa.Column(
            "compliance_profile_version",
            sa.String(length=50),
            server_default="1.0",
            nullable=False,
        ),
    )

    op.create_table(
        "customer_sessions",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("selected_location_id", sa.Uuid(), nullable=True),
        sa.Column("compliance_profile_id", sa.String(length=100), nullable=False),
        sa.Column(
            "compliance_profile_version", sa.String(length=50), nullable=False
        ),
        sa.Column(
            "age_gate_status",
            sa.String(length=32),
            server_default="NOT_REQUIRED",
            nullable=False,
        ),
        sa.Column("age_attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "age_gate_status IN "
            "('NOT_REQUIRED', 'REQUIRED_UNVERIFIED', 'VERIFIED', 'DENIED', 'EXPIRED')",
            name="ck_customer_sessions_age_gate_status",
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["selected_location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_customer_sessions_location_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_sessions_business_id", "customer_sessions", ["business_id"]
    )
    op.create_index(
        "ix_customer_sessions_selected_location_id",
        "customer_sessions",
        ["selected_location_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_sessions_selected_location_id",
        table_name="customer_sessions",
    )
    op.drop_index(
        "ix_customer_sessions_business_id", table_name="customer_sessions"
    )
    op.drop_table("customer_sessions")
    op.drop_column("businesses", "compliance_profile_version")
    op.drop_column("businesses", "compliance_profile_id")
