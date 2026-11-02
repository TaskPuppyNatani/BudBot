"""Audited local catalog writes; customer reads remain in CatalogService."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.catalog.currency import CURRENCY_MINOR_UNITS
from budbot.core.tenancy import TenantContext
from budbot.core.exceptions import DomainError
from budbot.core.time import utc_now
from budbot.schemas.catalog import CatalogRead, DealInput, DealRead, ProductInput, ProductRead, OfferingInput
from budbot.services.audit_service import record_audit_event
from budbot.services.catalog_repository import CatalogRepository
from budbot.services.business_service import BusinessService


class CatalogAdminService:
    def __init__(self, session: AsyncSession, tenant: TenantContext):
        self.session, self.tenant = session, tenant
        self.repo = CatalogRepository(session, tenant)

    async def _lock_scope(self):
        # One lock order for category creation, offering replacement and visibility.
        await BusinessService(self.session).get(self.tenant, self.tenant.business_id, for_update=True)

    async def product_read(self, product) -> ProductRead:
        category = await self.repo.categories.get(product.category_id, resource_name="category")
        rows = (await self.session.scalars(self.repo.offerings.select().where(
            self.repo.offerings.model.product_id == product.id
        ))).all()
        return ProductRead(id=product.id, name=product.name, category=category.name,
            brand=product.brand, description=product.description, enabled=product.enabled,
            offerings=[OfferingInput(location_id=row.location_id, offered=row.offered,
                availability=row.availability, currency=row.currency,
                price=Decimal(row.price_minor).scaleb(-CURRENCY_MINOR_UNITS[row.currency])
                if row.price_minor is not None else None) for row in rows])

    async def list_catalog(self) -> CatalogRead:
        products = (await self.session.scalars(self.repo.products.select().order_by(self.repo.products.model.name, self.repo.products.model.id))).all()
        deals = (await self.session.scalars(self.repo.deals.select().order_by(self.repo.deals.model.title, self.repo.deals.model.id))).all()
        return CatalogRead(products=[await self.product_read(row) for row in products],
            deals=[DealRead.model_validate(row) for row in deals], currencies=sorted(CURRENCY_MINOR_UNITS))

    async def _publish(self, user_id, kind, row, result, fields, action):
        await record_audit_event(self.session, f"admin.catalog.{kind}.{action}",
            actor_user_id=user_id, business_id=self.tenant.business_id,
            resource_type=f"catalog_{kind}", resource_id=row.id,
            details={"enabled": row.enabled, "changed_fields": ",".join(sorted(fields))})
        await self.session.commit()
        return result

    async def save_product(self, payload: ProductInput, user_id: UUID, product_id: UUID | None = None):
        # Serialize category creation and full offering replacements for this tenant.
        await self._lock_scope()
        product = await self.repo.products.get(product_id, resource_name="product", for_update=True) if product_id else None
        # Check every location before changing a product or any offering.
        for offering in payload.offerings:
            await self.repo.locations.get(offering.location_id, resource_name="location")
        category = await self.repo.get_or_create_category(payload.category)
        if not category.enabled:
            raise DomainError("This category is hidden. Choose a different category name.", code="CATALOG_CATEGORY_HIDDEN", status_code=409)
        values = dict(category_id=category.id, name=payload.name, brand=payload.brand,
            description=payload.description, enabled=payload.enabled, source="local", source_updated_at=utc_now())
        if product is None:
            product = await self.repo.create_product(**values)
        else:
            for key, value in values.items():
                setattr(product, key, value)
        existing = (await self.session.scalars(self.repo.offerings.select().where(
            self.repo.offerings.model.product_id == product.id))).all()
        by_location = {row.location_id: row for row in existing}
        # Full form replacement removes omitted location offers, retaining their facts.
        for row in existing:
            row.offered = False
        for offering in payload.offerings:
            await self.repo.set_offering(product_id=product.id, location_id=offering.location_id,
                offered=offering.offered, availability=offering.availability,
                price_minor=offering.price_minor, currency=offering.currency,
                quantity=by_location[offering.location_id].quantity if offering.location_id in by_location else None,
                source="local", source_updated_at=utc_now())
        await self.session.flush()
        result = await self.product_read(product)
        return await self._publish(user_id, "product", product, result, payload.model_fields_set,
            "updated" if product_id else "created")

    async def save_deal(self, payload: DealInput, user_id: UUID, deal_id: UUID | None = None):
        await self._lock_scope()
        row = await self.repo.deals.get(deal_id, resource_name="deal", for_update=True) if deal_id else None
        if payload.location_id:
            await self.repo.locations.get(payload.location_id, resource_name="location")
        if row is None:
            row = await self.repo.create_deal(**payload.model_dump(), source_updated_at=utc_now())
        else:
            for key, value in payload.model_dump().items():
                setattr(row, key, value)
            row.source, row.source_updated_at = "local", utc_now()
        await self.session.flush()
        return await self._publish(user_id, "deal", row, DealRead.model_validate(row), payload.model_fields_set,
            "updated" if deal_id else "created")

    async def set_visibility(self, kind: str, row_id: UUID, enabled: bool, user_id: UUID):
        await self._lock_scope()
        repository = self.repo.products if kind == "product" else self.repo.deals
        row = await repository.get(row_id, resource_name=kind, for_update=True)
        row.enabled = enabled
        await self.session.flush()
        result = await self.product_read(row) if kind == "product" else DealRead.model_validate(row)
        return await self._publish(user_id, kind, row, result, {"enabled"}, "restored" if enabled else "hidden")

    async def delete_product(self, product_id: UUID, user_id: UUID):
        await self._lock_scope()
        product = await self.repo.products.get(product_id, resource_name="product", for_update=True)
        # Existing composite tenant FKs cascade product offerings and product-linked
        # deals. Locations, categories and unrelated deals/products are retained.
        await self.session.delete(product)
        await self.session.flush()
        await record_audit_event(self.session, "admin.catalog.product.deleted",
            actor_user_id=user_id, business_id=self.tenant.business_id,
            resource_type="catalog_product", resource_id=product_id, details={})
        await self.session.commit()
