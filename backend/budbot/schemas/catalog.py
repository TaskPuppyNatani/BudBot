"""Owner-friendly local catalog inputs over the existing catalog schema."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from budbot.catalog.currency import CURRENCY_MINOR_UNITS, normalize_currency_code
from budbot.catalog.types import AvailabilityState
from budbot.schemas.common import DomainSchema, Name


class OfferingInput(DomainSchema):
    model_config = ConfigDict(extra="forbid")
    location_id: UUID
    offered: bool = True
    availability: AvailabilityState = AvailabilityState.UNKNOWN
    price: Decimal | None = Field(default=None, ge=0, max_digits=23, decimal_places=4, allow_inf_nan=False)
    currency: str | None = None

    @model_validator(mode="after")
    def validate_price(self):
        if self.price is None:
            if self.currency is not None:
                raise ValueError("Leave currency blank when no price is listed.")
        else:
            self.currency = normalize_currency_code(self.currency)
            if self.currency is None or not self.price.is_finite() or self.price < 0:
                raise ValueError("Enter a non-negative price and choose its currency.")
            minor = self.price * 10 ** CURRENCY_MINOR_UNITS[self.currency]
            if minor != minor.to_integral_value() or minor > 9223372036854775807:
                raise ValueError("Enter a price with the correct number of decimal places for its currency.")
        return self

    @property
    def price_minor(self) -> int | None:
        return None if self.price is None else int(self.price * 10 ** CURRENCY_MINOR_UNITS[self.currency])


class ProductInput(DomainSchema):
    model_config = ConfigDict(extra="forbid")
    name: Name
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] | None = None
    enabled: bool = True
    offerings: list[OfferingInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_locations(self):
        if len({row.location_id for row in self.offerings}) != len(self.offerings):
            raise ValueError("Choose each location only once.")
        return self


class VisibilityInput(DomainSchema):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class ProductRead(ProductInput):
    id: UUID


class DealInput(DomainSchema):
    model_config = ConfigDict(extra="forbid")
    title: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    location_id: UUID | None = None
    enabled: bool = True


class DealRead(DealInput):
    id: UUID


class CatalogRead(DomainSchema):
    products: list[ProductRead]
    deals: list[DealRead]
    currencies: list[str]
