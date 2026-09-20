"""Assistant configuration and effective-configuration schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from budbot.schemas.common import DomainSchema, HexColor, Name, ShortText


class AssistantCreate(DomainSchema):
    display_name: Name
    greeting: ShortText
    fallback_message: ShortText
    avatar_reference: str | None = Field(default=None, max_length=2048)
    primary_color_override: HexColor | None = None
    enabled: bool = True


class AssistantUpdate(DomainSchema):
    display_name: Name | None = None
    greeting: ShortText | None = None
    fallback_message: ShortText | None = None
    avatar_reference: str | None = Field(default=None, max_length=2048)
    primary_color_override: HexColor | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "AssistantUpdate":
        required = {"display_name", "greeting", "fallback_message", "enabled"}
        for field in required & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("at least one assistant field must be supplied")
        return self


class AssistantRead(DomainSchema):
    id: UUID
    business_id: UUID
    display_name: str
    greeting: str
    fallback_message: str
    avatar_reference: str | None
    primary_color_override: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class LocationAssistantOverrideUpdate(DomainSchema):
    display_name: Name | None = None
    greeting: ShortText | None = None
    fallback_message: ShortText | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_explicit_field(self) -> "LocationAssistantOverrideUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one override field must be supplied")
        return self


class LocationAssistantOverrideRead(DomainSchema):
    id: UUID
    business_id: UUID
    location_id: UUID
    display_name: str | None
    greeting: str | None
    fallback_message: str | None
    enabled: bool | None
    created_at: datetime
    updated_at: datetime


class EffectiveAssistantConfiguration(DomainSchema):
    assistant_id: UUID
    business_id: UUID
    location_id: UUID
    display_name: str
    greeting: str
    fallback_message: str
    avatar_reference: str | None
    primary_color: str | None
    enabled: bool
