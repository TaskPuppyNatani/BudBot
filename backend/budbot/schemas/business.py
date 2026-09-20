"""Business tenant request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from budbot.schemas.assistant import AssistantCreate
from budbot.schemas.common import (
    DomainSchema,
    HexColor,
    Industry,
    Name,
    validate_phone,
    validate_timezone,
)


class BusinessCreate(DomainSchema):
    display_name: Name
    legal_name: str | None = Field(default=None, max_length=250)
    industry: Industry
    website_url: AnyHttpUrl | None = None
    main_phone: str | None = None
    logo_reference: str | None = Field(default=None, max_length=2048)
    primary_brand_color: HexColor | None = None
    active: bool = True
    default_timezone: str | None = None
    assistant: AssistantCreate

    _phone = field_validator("main_phone")(validate_phone)
    _timezone = field_validator("default_timezone")(validate_timezone)


class BusinessUpdate(DomainSchema):
    display_name: Name | None = None
    legal_name: str | None = Field(default=None, max_length=250)
    industry: Industry | None = None
    website_url: AnyHttpUrl | None = None
    main_phone: str | None = None
    logo_reference: str | None = Field(default=None, max_length=2048)
    primary_brand_color: HexColor | None = None
    active: bool | None = None
    default_timezone: str | None = None

    _phone = field_validator("main_phone")(validate_phone)
    _timezone = field_validator("default_timezone")(validate_timezone)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "BusinessUpdate":
        required = {"display_name", "industry", "active"}
        for field in required & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("at least one business field must be supplied")
        return self


class BusinessRead(DomainSchema):
    id: UUID
    display_name: str
    legal_name: str | None
    industry: str
    website_url: str | None
    main_phone: str | None
    logo_reference: str | None
    primary_brand_color: str | None
    active: bool
    default_timezone: str | None
    created_at: datetime
    updated_at: datetime
