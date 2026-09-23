"""Add tenant-scoped provider-neutral products, offerings, and deals."""

from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0006_m6_provider_neutral_catalog"
down_revision: str | None = "0005_m55_jurisdictional_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("products_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "businesses",
        sa.Column("promotions_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    op.create_table(
        "catalog_categories",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=100), server_default="local", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "business_id", name="uq_catalog_categories_id_business"),
        sa.UniqueConstraint("business_id", "normalized_name", name="uq_catalog_categories_business_name"),
    )
    op.create_index("ix_catalog_categories_business_id", "catalog_categories", ["business_id"])
    op.create_index("ix_catalog_categories_business_enabled", "catalog_categories", ["business_id", "enabled"])

    op.create_table(
        "catalog_products",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=100), server_default="local", nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "business_id"],
            ["catalog_categories.id", "catalog_categories.business_id"],
            name="fk_catalog_products_category_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "business_id", name="uq_catalog_products_id_business"),
    )
    op.create_index("ix_catalog_products_business_id", "catalog_products", ["business_id"])
    op.create_index("ix_catalog_products_business_category", "catalog_products", ["business_id", "category_id"])
    op.create_index("ix_catalog_products_business_enabled", "catalog_products", ["business_id", "enabled"])

    op.create_table(
        "product_offerings",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("offered", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("availability", sa.String(length=20), server_default="unknown", nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=100), server_default="local", nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("availability IN ('available', 'unavailable', 'unknown')", name="ck_product_offerings_availability"),
        sa.CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_product_offerings_quantity"),
        sa.CheckConstraint(
            "(price_minor IS NULL AND currency IS NULL) OR "
            "(price_minor IS NOT NULL AND price_minor >= 0 AND currency IS NOT NULL)",
            name="ck_product_offerings_price_currency",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))",
            name="ck_product_offerings_currency_iso_shape",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency IN ("
            "'AED', 'ARS', 'AUD', 'BDT', 'BGN', 'BHD', 'BIF', 'BRL', 'CAD', "
            "'CHF', 'CLF', 'CLP', 'CNY', 'COP', 'CZK', 'DJF', 'DKK', "
            "'EGP', 'EUR', 'GBP', 'GHS', 'GNF', 'HKD', 'HUF', 'IDR', 'ILS', 'INR', "
            "'IQD', 'ISK', 'JOD', 'JPY', 'KES', 'KMF', 'KRW', 'KWD', 'LKR', 'LYD', "
            "'MAD', 'MXN', 'MYR', 'NGN', 'NOK', 'NPR', 'NZD', 'OMR', 'PEN', 'PHP', "
            "'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RUB', 'RWF', 'SAR', 'SEK', 'SGD', "
            "'THB', 'TND', 'TRY', 'TWD', 'UAH', 'UGX', 'USD', 'UYU', 'UYW', 'VND', "
            "'VUV', 'XAF', 'XOF', 'XPF', 'ZAR')",
            name="ck_product_offerings_currency_iso_supported",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_product_offerings_location_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["catalog_products.id", "catalog_products.business_id"],
            name="fk_product_offerings_product_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "location_id", "product_id",
            name="uq_product_offerings_business_location_product",
        ),
    )
    op.create_index("ix_product_offerings_business_id", "product_offerings", ["business_id"])
    op.create_index("ix_product_offerings_location_id", "product_offerings", ["location_id"])
    op.create_index("ix_product_offerings_product_id", "product_offerings", ["product_id"])
    op.create_index(
        "ix_product_offerings_business_location_offered",
        "product_offerings",
        ["business_id", "location_id", "offered"],
    )

    op.create_table(
        "catalog_deals",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=100), server_default="local", nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="ck_catalog_deals_valid_window",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_catalog_deals_location_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["catalog_products.id", "catalog_products.business_id"],
            name="fk_catalog_deals_product_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "business_id"],
            ["catalog_categories.id", "catalog_categories.business_id"],
            name="fk_catalog_deals_category_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_catalog_deals_business_id", "catalog_deals", ["business_id"])
    op.create_index("ix_catalog_deals_location_id", "catalog_deals", ["location_id"])
    op.create_index("ix_catalog_deals_product_id", "catalog_deals", ["product_id"])
    op.create_index("ix_catalog_deals_category_id", "catalog_deals", ["category_id"])
    op.create_index(
        "ix_catalog_deals_business_location_enabled",
        "catalog_deals",
        ["business_id", "location_id", "enabled"],
    )
    op.create_index(
        "ix_catalog_deals_business_window",
        "catalog_deals",
        ["business_id", "starts_at", "ends_at"],
    )


def downgrade() -> None:
    for name in (
        "ix_catalog_deals_business_window",
        "ix_catalog_deals_business_location_enabled",
        "ix_catalog_deals_category_id",
        "ix_catalog_deals_product_id",
        "ix_catalog_deals_location_id",
        "ix_catalog_deals_business_id",
    ):
        op.drop_index(name, table_name="catalog_deals")
    op.drop_table("catalog_deals")

    for name in (
        "ix_product_offerings_business_location_offered",
        "ix_product_offerings_product_id",
        "ix_product_offerings_location_id",
        "ix_product_offerings_business_id",
    ):
        op.drop_index(name, table_name="product_offerings")
    op.drop_table("product_offerings")

    for name in (
        "ix_catalog_products_business_enabled",
        "ix_catalog_products_business_category",
        "ix_catalog_products_business_id",
    ):
        op.drop_index(name, table_name="catalog_products")
    op.drop_table("catalog_products")

    for name in (
        "ix_catalog_categories_business_enabled",
        "ix_catalog_categories_business_id",
    ):
        op.drop_index(name, table_name="catalog_categories")
    op.drop_table("catalog_categories")
    op.drop_column("businesses", "promotions_enabled")
    op.drop_column("businesses", "products_enabled")
