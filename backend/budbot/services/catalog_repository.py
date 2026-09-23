"""Tenant-scoped persistence and read queries for the local catalog provider."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from budbot.catalog.types import AvailabilityState
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.catalog import (
    CatalogCategory,
    CatalogDeal,
    CatalogProduct,
    ProductOffering,
    normalize_catalog_text,
)
from budbot.models.location import Location


ProductRow = tuple[CatalogProduct, ProductOffering, CatalogCategory]
_LIKE_ESCAPE = "!"


def _literal_search_pattern(term: str) -> str:
    """Build a substring LIKE pattern while treating user text literally."""

    escaped = (
        term.lower()
        .replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def _literal_search_expression(
    field: ColumnElement[Any], term: str
) -> ColumnElement[bool]:
    """Return a parameterized, case-insensitive literal substring predicate."""

    return func.lower(field).like(
        _literal_search_pattern(term), escape=_LIKE_ESCAPE
    )


class CatalogRepository:
    """Central tenant predicate and persistence helpers for catalog records."""

    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.session = session
        self.tenant = tenant
        self.categories = TenantScopedRepository(session, CatalogCategory, tenant)
        self.products = TenantScopedRepository(session, CatalogProduct, tenant)
        self.offerings = TenantScopedRepository(session, ProductOffering, tenant)
        self.deals = TenantScopedRepository(session, CatalogDeal, tenant)
        self.locations = TenantScopedRepository(session, Location, tenant)

    async def create_category(
        self,
        name: str,
        *,
        enabled: bool = True,
        display_order: int = 0,
        source: str = "local",
    ) -> CatalogCategory:
        normalized = normalize_catalog_text(name)
        if not normalized:
            raise ValueError("category name is required")
        category = CatalogCategory(
            business_id=self.tenant.business_id,
            name=" ".join(name.split()),
            normalized_name=normalized,
            enabled=enabled,
            display_order=display_order,
            source=source,
        )
        self.session.add(category)
        await self.session.flush()
        return category

    async def get_or_create_category(
        self, name: str, *, display_order: int = 0, source: str = "local"
    ) -> CatalogCategory:
        normalized = normalize_catalog_text(name)
        existing = await self.session.scalar(
            self.categories.select().where(
                CatalogCategory.normalized_name == normalized
            )
        )
        if existing is not None:
            return existing
        return await self.create_category(
            name, display_order=display_order, source=source
        )

    async def create_product(
        self,
        *,
        category_id: UUID,
        name: str,
        brand: str | None = None,
        description: str | None = None,
        enabled: bool = True,
        source_id: str | None = None,
        source: str = "local",
        source_updated_at: datetime | None = None,
    ) -> CatalogProduct:
        await self.categories.get(category_id, resource_name="catalog category")
        if not name.strip():
            raise ValueError("product name is required")
        product = CatalogProduct(
            business_id=self.tenant.business_id,
            category_id=category_id,
            name=" ".join(name.split()),
            brand=brand.strip() if brand else None,
            description=description,
            enabled=enabled,
            source_id=source_id,
            source=source,
            source_updated_at=source_updated_at,
        )
        self.session.add(product)
        await self.session.flush()
        return product

    async def set_offering(
        self,
        *,
        location_id: UUID,
        product_id: UUID,
        offered: bool = True,
        availability: AvailabilityState | str = AvailabilityState.UNKNOWN,
        price_minor: int | None = None,
        currency: str | None = None,
        quantity: int | None = None,
        source: str = "local",
        source_updated_at: datetime | None = None,
    ) -> ProductOffering:
        await self.locations.get(location_id, resource_name="location")
        await self.products.get(product_id, resource_name="catalog product")
        availability_value = AvailabilityState(availability).value
        statement = self.offerings.select().where(
            ProductOffering.location_id == location_id,
            ProductOffering.product_id == product_id,
        )
        offering = await self.session.scalar(statement)
        values = {
            "offered": offered,
            "availability": availability_value,
            "price_minor": price_minor,
            "currency": currency,
            "quantity": quantity,
            "source": source,
            "source_updated_at": source_updated_at,
        }
        if offering is None:
            offering = ProductOffering(
                business_id=self.tenant.business_id,
                location_id=location_id,
                product_id=product_id,
                **values,
            )
            self.session.add(offering)
        else:
            for field, value in values.items():
                setattr(offering, field, value)
        await self.session.flush()
        return offering

    async def create_deal(
        self,
        *,
        title: str,
        description: str,
        location_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
        enabled: bool = True,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        source: str = "local",
        source_updated_at: datetime | None = None,
    ) -> CatalogDeal:
        if location_id is not None:
            await self.locations.get(location_id, resource_name="location")
        if product_id is not None:
            await self.products.get(product_id, resource_name="catalog product")
        if category_id is not None:
            await self.categories.get(category_id, resource_name="catalog category")
        if not title.strip() or not description.strip():
            raise ValueError("deal title and description are required")
        deal = CatalogDeal(
            business_id=self.tenant.business_id,
            location_id=location_id,
            product_id=product_id,
            category_id=category_id,
            title=" ".join(title.split()),
            description=description.strip(),
            enabled=enabled,
            starts_at=starts_at,
            ends_at=ends_at,
            source=source,
            source_updated_at=source_updated_at,
        )
        self.session.add(deal)
        await self.session.flush()
        return deal

    async def offered_products(
        self,
        location_id: UUID,
        *,
        limit: int,
        category_normalized: str | None = None,
        search_terms: tuple[str, ...] = (),
    ) -> list[ProductRow]:
        statement = (
            select(CatalogProduct, ProductOffering, CatalogCategory)
            .join(
                ProductOffering,
                and_(
                    ProductOffering.product_id == CatalogProduct.id,
                    ProductOffering.business_id == CatalogProduct.business_id,
                ),
            )
            .join(
                CatalogCategory,
                and_(
                    CatalogCategory.id == CatalogProduct.category_id,
                    CatalogCategory.business_id == CatalogProduct.business_id,
                ),
            )
            .where(
                CatalogProduct.business_id == self.tenant.business_id,
                ProductOffering.business_id == self.tenant.business_id,
                CatalogCategory.business_id == self.tenant.business_id,
                ProductOffering.location_id == location_id,
                ProductOffering.offered.is_(True),
                CatalogProduct.enabled.is_(True),
                CatalogCategory.enabled.is_(True),
            )
        )
        if category_normalized is not None:
            statement = statement.where(
                CatalogCategory.normalized_name == category_normalized
            )
        if search_terms:
            fields = (
                CatalogProduct.name,
                CatalogProduct.brand,
                CatalogProduct.description,
                CatalogCategory.name,
            )
            for term in search_terms:
                statement = statement.where(
                    or_(
                        *(
                            _literal_search_expression(field, term)
                            for field in fields
                        )
                    )
                )
        statement = statement.order_by(
            func.lower(CatalogProduct.name),
            func.lower(CatalogCategory.name),
            CatalogProduct.id,
        ).limit(limit)
        rows = (await self.session.execute(statement)).all()
        return [(product, offering, category) for product, offering, category in rows]

    async def visible_categories(
        self, location_id: UUID, *, limit: int
    ) -> list[CatalogCategory]:
        statement = (
            select(CatalogCategory)
            .join(
                CatalogProduct,
                and_(
                    CatalogProduct.category_id == CatalogCategory.id,
                    CatalogProduct.business_id == CatalogCategory.business_id,
                ),
            )
            .join(
                ProductOffering,
                and_(
                    ProductOffering.product_id == CatalogProduct.id,
                    ProductOffering.business_id == CatalogProduct.business_id,
                ),
            )
            .where(
                CatalogCategory.business_id == self.tenant.business_id,
                CatalogProduct.business_id == self.tenant.business_id,
                ProductOffering.business_id == self.tenant.business_id,
                CatalogCategory.enabled.is_(True),
                CatalogProduct.enabled.is_(True),
                ProductOffering.offered.is_(True),
                ProductOffering.location_id == location_id,
            )
            .distinct()
            .order_by(CatalogCategory.display_order, func.lower(CatalogCategory.name), CatalogCategory.id)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def active_deals(
        self, location_id: UUID, *, as_of: datetime, limit: int
    ) -> list[CatalogDeal]:
        visible_linked_product = exists(
            select(1)
            .select_from(CatalogProduct)
            .join(
                CatalogCategory,
                and_(
                    CatalogCategory.id == CatalogProduct.category_id,
                    CatalogCategory.business_id == CatalogProduct.business_id,
                ),
            )
            .join(
                ProductOffering,
                and_(
                    ProductOffering.product_id == CatalogProduct.id,
                    ProductOffering.business_id == CatalogProduct.business_id,
                ),
            )
            .where(
                CatalogProduct.id == CatalogDeal.product_id,
                CatalogProduct.business_id == self.tenant.business_id,
                CatalogProduct.enabled.is_(True),
                CatalogCategory.enabled.is_(True),
                ProductOffering.business_id == self.tenant.business_id,
                ProductOffering.location_id == location_id,
                ProductOffering.offered.is_(True),
            )
        )
        visible_linked_category = exists(
            select(1)
            .select_from(CatalogCategory)
            .join(
                CatalogProduct,
                and_(
                    CatalogProduct.category_id == CatalogCategory.id,
                    CatalogProduct.business_id == CatalogCategory.business_id,
                ),
            )
            .join(
                ProductOffering,
                and_(
                    ProductOffering.product_id == CatalogProduct.id,
                    ProductOffering.business_id == CatalogProduct.business_id,
                ),
            )
            .where(
                CatalogCategory.id == CatalogDeal.category_id,
                CatalogCategory.business_id == self.tenant.business_id,
                CatalogCategory.enabled.is_(True),
                CatalogProduct.business_id == self.tenant.business_id,
                CatalogProduct.enabled.is_(True),
                ProductOffering.business_id == self.tenant.business_id,
                ProductOffering.location_id == location_id,
                ProductOffering.offered.is_(True),
            )
        )
        statement = (
            self.deals.select()
            .where(
                CatalogDeal.enabled.is_(True),
                or_(CatalogDeal.location_id.is_(None), CatalogDeal.location_id == location_id),
                or_(CatalogDeal.product_id.is_(None), visible_linked_product),
                or_(CatalogDeal.category_id.is_(None), visible_linked_category),
                or_(CatalogDeal.starts_at.is_(None), CatalogDeal.starts_at <= as_of),
                or_(CatalogDeal.ends_at.is_(None), CatalogDeal.ends_at > as_of),
            )
            .order_by(func.lower(CatalogDeal.title), CatalogDeal.id)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())
