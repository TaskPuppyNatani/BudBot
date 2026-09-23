"""Stable catalog values that do not expose provider implementation details."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProductResult:
    id: UUID
    name: str
    brand: str | None
    category: str
    description: str | None
    availability: AvailabilityState
    price_minor: int | None
    currency: str | None
    quantity: int | None
    product_source: str
    product_source_updated_at: datetime | None
    offering_source: str
    offering_source_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class CategoryResult:
    id: UUID
    name: str
    display_order: int
    source: str


@dataclass(frozen=True, slots=True)
class DealResult:
    id: UUID
    title: str
    description: str
    starts_at: datetime | None
    ends_at: datetime | None
    source: str
    source_updated_at: datetime | None


ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class CatalogPage(Generic[ResultT]):
    items: tuple[ResultT, ...]
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class CatalogResult(Generic[ResultT]):
    location_id: UUID
    location_name: str
    items: tuple[ResultT, ...]
    has_more: bool


class CatalogError(Exception):
    """Internal normalized provider/catalog failure without unsafe details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
