"""Add the M2 tenant and multi-location domain.

Revision ID: 0002_m2_tenant_domain
Revises: 0001_m1_baseline
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_m2_tenant_domain"
down_revision: str | None = "0001_m1_baseline"
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
    op.create_table(
        "businesses",
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", sa.String(length=250), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("main_phone", sa.String(length=40), nullable=True),
        sa.Column("logo_reference", sa.String(length=2048), nullable=True),
        sa.Column("primary_brand_color", sa.String(length=7), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("default_timezone", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_accounts",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "assistant_configurations",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("greeting", sa.String(length=1000), nullable=False),
        sa.Column("fallback_message", sa.String(length=1000), nullable=False),
        sa.Column("avatar_reference", sa.String(length=2048), nullable=True),
        sa.Column("primary_color_override", sa.String(length=7), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_table(
        "business_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "business_id", name="uq_business_memberships_user_business"
        ),
    )
    op.create_index(
        "ix_business_memberships_business_id", "business_memberships", ["business_id"]
    )
    op.create_index(
        "ix_business_memberships_user_id", "business_memberships", ["user_id"]
    )

    op.create_table(
        "locations",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("address_line_1", sa.String(length=250), nullable=False),
        sa.Column("address_line_2", sa.String(length=250), nullable=True),
        sa.Column("city", sa.String(length=150), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("postal_code", sa.String(length=30), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("maps_place_id", sa.String(length=255), nullable=True),
        sa.Column("maps_destination", sa.String(length=2048), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "business_id", name="uq_locations_id_business"),
    )
    op.create_index("ix_locations_business_id", "locations", ["business_id"])

    op.create_table(
        "location_hours",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_location_hours_day_of_week",
        ),
        sa.CheckConstraint(
            "(is_closed AND open_time IS NULL AND close_time IS NULL) OR "
            "(NOT is_closed AND open_time IS NOT NULL AND close_time IS NOT NULL "
            "AND open_time < close_time)",
            name="ck_location_hours_valid_range",
        ),
        sa.ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_location_hours_location_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "location_id", "day_of_week", name="uq_location_hours_location_day"
        ),
    )
    op.create_index(
        "ix_location_hours_business_id", "location_hours", ["business_id"]
    )
    op.create_index(
        "ix_location_hours_location_id", "location_hours", ["location_id"]
    )

    op.create_table(
        "location_assistant_overrides",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("greeting", sa.String(length=1000), nullable=True),
        sa.Column("fallback_message", sa.String(length=1000), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_location_assistant_overrides_location_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "location_id", name="uq_location_assistant_overrides_location"
        ),
    )
    op.create_index(
        "ix_location_assistant_overrides_business_id",
        "location_assistant_overrides",
        ["business_id"],
    )

def downgrade() -> None:
    op.drop_index(
        "ix_location_assistant_overrides_business_id",
        table_name="location_assistant_overrides",
    )
    op.drop_table("location_assistant_overrides")
    op.drop_index("ix_location_hours_location_id", table_name="location_hours")
    op.drop_index("ix_location_hours_business_id", table_name="location_hours")
    op.drop_table("location_hours")
    op.drop_index("ix_locations_business_id", table_name="locations")
    op.drop_table("locations")
    op.drop_index(
        "ix_business_memberships_user_id", table_name="business_memberships"
    )
    op.drop_index(
        "ix_business_memberships_business_id", table_name="business_memberships"
    )
    op.drop_table("business_memberships")
    op.drop_table("assistant_configurations")
    op.drop_table("user_accounts")
    op.drop_table("businesses")
