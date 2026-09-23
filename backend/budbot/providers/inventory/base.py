"""Provider-neutral contract and explicit catalog-provider registry."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol
from uuid import UUID

from budbot.catalog.types import (
    CatalogPage,
    CategoryResult,
    DealResult,
    ProductResult,
)


@dataclass(frozen=True, slots=True)
class CatalogProviderContext:
    """Server-resolved scope supplied to a provider for one catalog operation."""

    business_id: UUID
    location_id: UUID
    as_of: datetime
    result_limit: int


class CatalogProvider(Protocol):
    """Normalized catalog operations expected of every catalog provider."""

    async def list_products(
        self, context: CatalogProviderContext, *, category: str | None
    ) -> CatalogPage[ProductResult]: ...

    async def search_products(
        self, context: CatalogProviderContext, *, query: str
    ) -> CatalogPage[ProductResult]: ...

    async def list_categories(
        self, context: CatalogProviderContext
    ) -> CatalogPage[CategoryResult]: ...

    async def list_deals(
        self, context: CatalogProviderContext
    ) -> CatalogPage[DealResult]: ...


class CatalogProviderRegistry:
    """Explicit, server-controlled lookup; user input is never imported/executed."""

    _KEY = re.compile(r"^[a-z][a-z0-9_]{0,49}$")

    def __init__(self, providers: Mapping[str, CatalogProvider] | None = None) -> None:
        self._providers: dict[str, CatalogProvider] = {}
        for key, provider in (providers or {}).items():
            self.register(key, provider)

    def register(self, key: str, provider: CatalogProvider) -> None:
        normalized = key.strip().lower()
        if not self._KEY.fullmatch(normalized):
            raise ValueError("catalog provider key is invalid")
        if normalized in self._providers:
            raise ValueError("catalog provider key is already registered")
        self._providers[normalized] = provider

    def resolve(self, key: str) -> CatalogProvider:
        normalized = key.strip().lower()
        if not self._KEY.fullmatch(normalized):
            from budbot.catalog.types import CatalogError

            raise CatalogError("CATALOG_PROVIDER_UNKNOWN")
        provider = self._providers.get(normalized)
        if provider is None:
            from budbot.catalog.types import CatalogError

            raise CatalogError("CATALOG_PROVIDER_UNKNOWN")
        return provider
