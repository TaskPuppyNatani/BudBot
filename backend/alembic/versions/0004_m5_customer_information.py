"""Add explicit M5 customer information and capability flags."""

from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0004_m5_customer_information"
down_revision: str | None = "0003_m3_sessions_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEATURE_COLUMNS = (
    "directions_enabled",
    "faq_enabled",
    "payments_info_enabled",
    "policies_info_enabled",
)
FAQ_INDEXES = (
    ("ix_faq_entries_business_id", ["business_id"]),
    ("ix_faq_entries_location_id", ["location_id"]),
    ("ix_faq_entries_business_location", ["business_id", "location_id"]),
)


def upgrade() -> None:
    op.add_column("businesses", sa.Column("payment_methods", sa.JSON(), nullable=True))
    op.add_column("businesses", sa.Column("store_policies", sa.JSON(), nullable=True))
    for feature in FEATURE_COLUMNS:
        op.add_column(
            "businesses",
            sa.Column(feature, sa.Boolean(), server_default=sa.true(), nullable=False),
        )
    op.create_table(
        "faq_entries",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_faq_entries_location_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in FAQ_INDEXES:
        op.create_index(name, "faq_entries", columns)


def downgrade() -> None:
    for name, _columns in reversed(FAQ_INDEXES):
        op.drop_index(name, table_name="faq_entries")
    op.drop_table("faq_entries")
    for feature in reversed(FEATURE_COLUMNS):
        op.drop_column("businesses", feature)
    op.drop_column("businesses", "store_policies")
    op.drop_column("businesses", "payment_methods")
