"""Authoritative tenant/location orchestration for customer catalog reads."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.catalog.types import (
    CatalogError,
    CatalogPage,
    CatalogResult,
    CategoryResult,
    DealResult,
    ProductResult,
)
from budbot.models.catalog import normalize_catalog_text
from budbot.core.exceptions import CommandError
from budbot.core.tenancy import TenantContext
from budbot.core.time import ensure_utc, utc_now
from budbot.database.tenant import TenantScopedRepository
from budbot.models.location import Location
from budbot.providers.inventory.base import (
    CatalogProvider,
    CatalogProviderContext,
    CatalogProviderRegistry,
)
from budbot.providers.inventory.local import LocalCatalogProvider
from budbot.services.catalog_repository import CatalogRepository


MAX_CATALOG_RESULTS = 25
ResultT = TypeVar("ResultT")


def build_catalog_provider_registry(
    local_repository: CatalogRepository,
) -> CatalogProviderRegistry:
    """Return the explicit server-side provider set available in M6."""

    registry = CatalogProviderRegistry()
    registry.register("local", LocalCatalogProvider(local_repository))
    return registry


class CatalogService:
    """Resolve scope/provider once and normalize bounded catalog results."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        *,
        provider_key: str = "local",
        providers: CatalogProviderRegistry | None = None,
        provider_key_resolver: Callable[[TenantContext, Location], str] | None = None,
        clock: Callable[[], datetime] = utc_now,
        result_limit: int = MAX_CATALOG_RESULTS,
    ) -> None:
        if result_limit < 1:
            raise ValueError("catalog result limit must be positive")
        self.session = session
        self.tenant = tenant
        self.provider_key = provider_key
        self.provider_key_resolver = provider_key_resolver or (
            lambda _tenant, _location: self.provider_key
        )
        self.clock = clock
        self.result_limit = result_limit
        self.locations = TenantScopedRepository(session, Location, tenant)
        self.repository = CatalogRepository(session, tenant)
        self.providers = (
            providers
            if providers is not None
            else build_catalog_provider_registry(self.repository)
        )

    async def list_products(
        self, selected_location_id: UUID | None, *, category: str | None = None
    ) -> CatalogResult[ProductResult]:
        location, context, provider = await self._prepare(selected_location_id)
        page = await self._provider_call(
            provider.list_products(context, category=category)
        )
        return self._result(
            location,
            page,
            lambda item: (
                item.name.casefold(),
                (item.brand or "").casefold(),
                item.category.casefold(),
                item.id.hex,
            ),
        )

    async def search_products(
        self, selected_location_id: UUID | None, query: str
    ) -> CatalogResult[ProductResult]:
        normalized_query = query.strip()
        if not normalized_query:
            raise CommandError(
                "CATALOG_QUERY_REQUIRED",
                "Enter search terms after /search, for example /search Blue Dream.",
            )
        location, context, provider = await self._prepare(selected_location_id)
        page = await self._provider_call(
            provider.search_products(context, query=normalized_query)
        )
        return self._result(
            location,
            page,
            lambda item: (
                item.name.casefold(),
                (item.brand or "").casefold(),
                item.category.casefold(),
                item.id.hex,
            ),
        )

    async def list_categories(
        self, selected_location_id: UUID | None
    ) -> CatalogResult[CategoryResult]:
        location, context, provider = await self._prepare(selected_location_id)
        page = await self._provider_call(provider.list_categories(context))
        seen: set[str] = set()
        unique: list[CategoryResult] = []
        for item in page.items[: self.result_limit + 1]:
            identity = normalize_catalog_text(item.name)
            if identity and identity not in seen:
                seen.add(identity)
                unique.append(item)
        page = CatalogPage(
            tuple(unique),
            has_more=page.has_more or len(page.items) > self.result_limit,
        )
        return self._result(
            location,
            page,
            lambda item: (item.display_order, item.name.casefold(), item.id.hex),
        )

    async def list_deals(
        self, selected_location_id: UUID | None
    ) -> CatalogResult[DealResult]:
        location, context, provider = await self._prepare(selected_location_id)
        page = await self._provider_call(provider.list_deals(context))
        active: list[DealResult] = []
        for deal in page.items[: self.result_limit + 1]:
            starts_at = self._deal_time(deal.starts_at)
            ends_at = self._deal_time(deal.ends_at)
            if (starts_at is None or starts_at <= context.as_of) and (
                ends_at is None or ends_at > context.as_of
            ):
                active.append(
                    replace(deal, starts_at=starts_at, ends_at=ends_at)
                )
        page = CatalogPage(
            tuple(active),
            has_more=page.has_more or len(page.items) > self.result_limit,
        )
        return self._result(
            location,
            page,
            lambda item: (item.title.casefold(), item.id.hex),
        )

    async def _prepare(
        self, selected_location_id: UUID | None
    ) -> tuple[Location, CatalogProviderContext, CatalogProvider]:
        if selected_location_id is None:
            raise CommandError(
                "CATALOG_LOCATION_REQUIRED",
                "Select a location with /location <name>. Use /locations to see active locations.",
                status_code=409,
            )
        location = await self.locations.get(
            selected_location_id, resource_name="location"
        )
        if not location.active:
            raise CommandError(
                "LOCATION_INACTIVE",
                "Your selected location is no longer active. Select another with /location <name>.",
                status_code=409,
            )
        try:
            provider_key = self.provider_key_resolver(self.tenant, location)
            provider = self.providers.resolve(provider_key)
        except CatalogError as exc:
            raise CommandError(
                "CATALOG_PROVIDER_UNKNOWN",
                "the catalog provider is not available",
                status_code=503,
            ) from exc
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("catalog clock must return a timezone-aware datetime")
        context = CatalogProviderContext(
            business_id=self.tenant.business_id,
            location_id=location.id,
            as_of=ensure_utc(now),
            result_limit=self.result_limit,
        )
        return location, context, provider

    @staticmethod
    async def _provider_call(
        awaitable: Awaitable[CatalogPage[ResultT]],
    ) -> CatalogPage[ResultT]:
        try:
            return await awaitable
        except CatalogError as exc:
            raise CommandError(
                "CATALOG_PROVIDER_UNAVAILABLE",
                "catalog data is temporarily unavailable",
                status_code=503,
            ) from exc
        except Exception as exc:
            # Provider exceptions may contain internal URLs, credentials, or
            # vendor response details. Normalize them before customer output.
            raise CommandError(
                "CATALOG_PROVIDER_UNAVAILABLE",
                "catalog data is temporarily unavailable",
                status_code=503,
            ) from exc

    @staticmethod
    def _deal_time(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise CommandError(
                "CATALOG_PROVIDER_UNAVAILABLE",
                "catalog data is temporarily unavailable",
                status_code=503,
            )
        return ensure_utc(value)

    def _result(
        self,
        location: Location,
        page: CatalogPage[ResultT],
        sort_key: Callable[[ResultT], tuple],
    ) -> CatalogResult[ResultT]:
        has_more = page.has_more or len(page.items) > self.result_limit
        bounded = page.items[: self.result_limit + 1]
        ordered = tuple(sorted(bounded, key=sort_key))
        return CatalogResult(
            location_id=location.id,
            location_name=location.display_name,
            items=ordered[: self.result_limit],
            has_more=has_more,
        )
