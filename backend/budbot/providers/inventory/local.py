"""Database-backed local/manual provider used when no POS adapter is configured."""

from budbot.catalog.types import (
    AvailabilityState,
    CatalogPage,
    CategoryResult,
    DealResult,
    ProductResult,
)
from budbot.core.time import ensure_utc
from budbot.models.catalog import normalize_catalog_text
from budbot.providers.inventory.base import CatalogProviderContext
from budbot.services.catalog_repository import CatalogRepository


class LocalCatalogProvider:
    """Read factual products and promotions maintained in BudBot's database."""

    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    @staticmethod
    def _product_result(product, offering, category) -> ProductResult:
        return ProductResult(
            id=product.id,
            name=product.name,
            brand=product.brand,
            category=category.name,
            description=product.description,
            availability=AvailabilityState(offering.availability),
            price_minor=offering.price_minor,
            currency=offering.currency,
            quantity=offering.quantity,
            product_source=product.source,
            product_source_updated_at=(
                ensure_utc(product.source_updated_at)
                if product.source_updated_at is not None
                else None
            ),
            offering_source=offering.source,
            offering_source_updated_at=(
                ensure_utc(offering.source_updated_at)
                if offering.source_updated_at is not None
                else None
            ),
        )

    async def list_products(
        self, context: CatalogProviderContext, *, category: str | None
    ) -> CatalogPage[ProductResult]:
        rows = await self.repository.offered_products(
            context.location_id,
            limit=context.result_limit + 1,
            category_normalized=(
                normalize_catalog_text(category) if category is not None else None
            ),
        )
        return CatalogPage(
            tuple(self._product_result(*row) for row in rows[: context.result_limit]),
            has_more=len(rows) > context.result_limit,
        )

    async def search_products(
        self, context: CatalogProviderContext, *, query: str
    ) -> CatalogPage[ProductResult]:
        terms = tuple(term for term in query.split() if term)
        rows = await self.repository.offered_products(
            context.location_id,
            limit=context.result_limit + 1,
            search_terms=terms,
        )
        return CatalogPage(
            tuple(self._product_result(*row) for row in rows[: context.result_limit]),
            has_more=len(rows) > context.result_limit,
        )

    async def list_categories(
        self, context: CatalogProviderContext
    ) -> CatalogPage[CategoryResult]:
        categories = await self.repository.visible_categories(
            context.location_id, limit=context.result_limit + 1
        )
        return CatalogPage(
            tuple(
                CategoryResult(
                    id=category.id,
                    name=category.name,
                    display_order=category.display_order,
                    source=category.source,
                )
                for category in categories[: context.result_limit]
            ),
            has_more=len(categories) > context.result_limit,
        )

    async def list_deals(
        self, context: CatalogProviderContext
    ) -> CatalogPage[DealResult]:
        deals = await self.repository.active_deals(
            context.location_id,
            as_of=context.as_of,
            limit=context.result_limit + 1,
        )
        return CatalogPage(
            tuple(
                DealResult(
                    id=deal.id,
                    title=deal.title,
                    description=deal.description,
                    starts_at=(ensure_utc(deal.starts_at) if deal.starts_at else None),
                    ends_at=(ensure_utc(deal.ends_at) if deal.ends_at else None),
                    source=deal.source,
                    source_updated_at=(
                        ensure_utc(deal.source_updated_at)
                        if deal.source_updated_at
                        else None
                    ),
                )
                for deal in deals[: context.result_limit]
            ),
            has_more=len(deals) > context.result_limit,
        )
