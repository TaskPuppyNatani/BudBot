"""Location and normalized weekly-hours schemas."""

from datetime import datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from budbot.schemas.common import (
    AddressLine,
    City,
    CountryCode,
    DomainSchema,
    Name,
    PostalCode,
    Region,
    validate_phone,
    validate_timezone,
)

RegionCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]


class LocationHoursInput(DomainSchema):
    day_of_week: int = Field(
        ge=0, le=6, description="ISO weekday index: Monday=0 through Sunday=6"
    )
    open_time: time | None = None
    close_time: time | None = None
    is_closed: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "LocationHoursInput":
        if self.is_closed:
            if self.open_time is not None or self.close_time is not None:
                raise ValueError("closed days cannot include open or close times")
            return self
        if self.open_time is None or self.close_time is None:
            raise ValueError("open days require both open_time and close_time")
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be earlier than close_time")
        return self


class LocationHoursRead(LocationHoursInput):
    id: UUID
    business_id: UUID
    location_id: UUID
    created_at: datetime
    updated_at: datetime


class LocationCreate(DomainSchema):
    display_name: Name
    address_line_1: AddressLine
    address_line_2: str | None = Field(default=None, max_length=250)
    city: City
    region: Region
    postal_code: PostalCode
    country: CountryCode
    region_code: RegionCode | None = None
    phone: str | None = None
    timezone: str
    active: bool = True
    maps_place_id: str | None = Field(default=None, max_length=255)
    maps_destination: str | None = Field(default=None, max_length=2048)
    hours: list[LocationHoursInput] = Field(default_factory=list, max_length=7)

    _phone = field_validator("phone")(validate_phone)
    _timezone = field_validator("timezone")(validate_timezone)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("region_code")
    @classmethod
    def normalize_region_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("hours")
    @classmethod
    def unique_days(cls, value: list[LocationHoursInput]) -> list[LocationHoursInput]:
        days = [item.day_of_week for item in value]
        if len(days) != len(set(days)):
            raise ValueError("hours may include at most one row per day")
        return value


class LocationUpdate(DomainSchema):
    display_name: Name | None = None
    address_line_1: AddressLine | None = None
    address_line_2: str | None = Field(default=None, max_length=250)
    city: City | None = None
    region: Region | None = None
    postal_code: PostalCode | None = None
    country: CountryCode | None = None
    region_code: RegionCode | None = None
    phone: str | None = None
    timezone: str | None = None
    active: bool | None = None
    maps_place_id: str | None = Field(default=None, max_length=255)
    maps_destination: str | None = Field(default=None, max_length=2048)
    hours: list[LocationHoursInput] | None = Field(default=None, max_length=7)

    _phone = field_validator("phone")(validate_phone)
    _timezone = field_validator("timezone")(validate_timezone)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("region_code")
    @classmethod
    def normalize_region_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("hours")
    @classmethod
    def unique_days(
        cls, value: list[LocationHoursInput] | None
    ) -> list[LocationHoursInput] | None:
        if value is None:
            return None
        days = [item.day_of_week for item in value]
        if len(days) != len(set(days)):
            raise ValueError("hours may include at most one row per day")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> "LocationUpdate":
        required = {
            "display_name",
            "address_line_1",
            "city",
            "region",
            "postal_code",
            "country",
            "timezone",
            "active",
            "hours",
        }
        for field in required & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("at least one location field must be supplied")
        return self


class LocationRead(DomainSchema):
    id: UUID
    business_id: UUID
    display_name: str
    address_line_1: str
    address_line_2: str | None
    city: str
    region: str
    postal_code: str
    country: str
    region_code: str | None
    phone: str | None
    timezone: str
    active: bool
    maps_place_id: str | None
    maps_destination: str | None
    hours: list[LocationHoursRead]
    created_at: datetime
    updated_at: datetime
