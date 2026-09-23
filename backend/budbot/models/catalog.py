"""Tenant-owned, provider-neutral catalog records."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from budbot.catalog.currency import normalize_currency_code
from budbot.catalog.currency import CURRENCY_MINOR_UNITS


_SUPPORTED_CURRENCIES_SQL = ", ".join(
    f"'{code}'" for code in CURRENCY_MINOR_UNITS
)


def normalize_catalog_text(value: str) -> str:
    """Collapse whitespace and case-fold a category identity consistently."""

    return " ".join(value.split()).casefold()


class CatalogCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant's normalized category identity and display order."""

    __tablename__ = "catalog_categories"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_catalog_categories_id_business"),
        UniqueConstraint(
            "business_id", "normalized_name", name="uq_catalog_categories_business_name"
        ),
        Index("ix_catalog_categories_business_enabled", "business_id", "enabled"),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    display_order: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(100), default="local", server_default="local", nullable=False
    )


class CatalogProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Industry-neutral factual product identity, owned by one business."""

    __tablename__ = "catalog_products"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_catalog_products_id_business"),
        ForeignKeyConstraint(
            ["category_id", "business_id"],
            ["catalog_categories.id", "catalog_categories.business_id"],
            name="fk_catalog_products_category_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_catalog_products_business_category", "business_id", "category_id"),
        Index("ix_catalog_products_business_enabled", "business_id", "enabled"),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(
        String(100), default="local", server_default="local", nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("source_updated_at")
    def normalize_source_timestamp(
        self, _key: str, value: datetime | None
    ) -> datetime | None:
        return _normalize_aware_utc(value)


class ProductOffering(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A product's explicit per-location offer, price, and availability facts."""

    __tablename__ = "product_offerings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_product_offerings_location_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["catalog_products.id", "catalog_products.business_id"],
            name="fk_product_offerings_product_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "business_id", "location_id", "product_id",
            name="uq_product_offerings_business_location_product",
        ),
        CheckConstraint(
            "availability IN ('available', 'unavailable', 'unknown')",
            name="ck_product_offerings_availability",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity >= 0", name="ck_product_offerings_quantity"
        ),
        CheckConstraint(
            "(price_minor IS NULL AND currency IS NULL) OR "
            "(price_minor IS NOT NULL AND price_minor >= 0 AND currency IS NOT NULL)",
            name="ck_product_offerings_price_currency",
        ),
        CheckConstraint(
            "currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))",
            name="ck_product_offerings_currency_iso_shape",
        ),
        CheckConstraint(
            f"currency IS NULL OR currency IN ({_SUPPORTED_CURRENCIES_SQL})",
            name="ck_product_offerings_currency_iso_supported",
        ),
        Index(
            "ix_product_offerings_business_location_offered",
            "business_id", "location_id", "offered",
        ),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    offered: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    availability: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False
    )
    price_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    quantity: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(100), default="local", server_default="local", nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("currency")
    def normalize_currency(self, _key: str, value: str | None) -> str | None:
        return normalize_currency_code(value)

    @validates("source_updated_at")
    def normalize_source_timestamp(
        self, _key: str, value: datetime | None
    ) -> datetime | None:
        return _normalize_aware_utc(value)


class CatalogDeal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bounded factual promotion configured for a business or location."""

    __tablename__ = "catalog_deals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_catalog_deals_location_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["catalog_products.id", "catalog_products.business_id"],
            name="fk_catalog_deals_product_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "business_id"],
            ["catalog_categories.id", "catalog_categories.business_id"],
            name="fk_catalog_deals_category_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="ck_catalog_deals_valid_window",
        ),
        Index("ix_catalog_deals_business_location_enabled", "business_id", "location_id", "enabled"),
        Index("ix_catalog_deals_business_window", "business_id", "starts_at", "ends_at"),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    product_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    category_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(
        String(100), default="local", server_default="local", nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("starts_at", "ends_at", "source_updated_at")
    def require_aware_utc(self, _key: str, value: datetime | None) -> datetime | None:
        return _normalize_aware_utc(value)


def _normalize_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("catalog timestamps must be timezone-aware")
    return value.astimezone(UTC)
