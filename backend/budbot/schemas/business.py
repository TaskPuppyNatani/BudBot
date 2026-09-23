"""Business tenant request and response schemas."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from budbot.schemas.assistant import AssistantCreate
from budbot.schemas.common import (
    DomainSchema,
    HexColor,
    Industry,
    Name,
    validate_phone,
    validate_timezone,
)


class PaymentMethod(DomainSchema):
    """A configured public payment method and optional plain-text detail."""

    name: Name
    details: str | None = Field(default=None, max_length=500)


class StorePolicy(DomainSchema):
    """A short, declarative customer-facing policy entry."""

    title: Name
    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]


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
    payment_methods: list[PaymentMethod] | None = Field(default=None, max_length=50)
    store_policies: list[StorePolicy] | None = Field(default=None, max_length=50)
    directions_enabled: bool = True
    faq_enabled: bool = True
    payments_info_enabled: bool = True
    policies_info_enabled: bool = True
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
    payment_methods: list[PaymentMethod] | None = Field(default=None, max_length=50)
    store_policies: list[StorePolicy] | None = Field(default=None, max_length=50)
    directions_enabled: bool | None = None
    faq_enabled: bool | None = None
    payments_info_enabled: bool | None = None
    policies_info_enabled: bool | None = None

    _phone = field_validator("main_phone")(validate_phone)
    _timezone = field_validator("default_timezone")(validate_timezone)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "BusinessUpdate":
        required = {
            "display_name",
            "industry",
            "active",
            "directions_enabled",
            "faq_enabled",
            "payments_info_enabled",
            "policies_info_enabled",
        }
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
    payment_methods: list[PaymentMethod] | None
    store_policies: list[StorePolicy] | None
    directions_enabled: bool
    faq_enabled: bool
    payments_info_enabled: bool
    policies_info_enabled: bool
    compliance_profile_id: str
    compliance_profile_version: str
    created_at: datetime
    updated_at: datetime
