"""Explicit customer-facing widget fields, independent of admin schemas."""

from uuid import UUID

from budbot.schemas.common import DomainSchema


class WidgetBusinessRead(DomainSchema):
    display_name: str
    logo_reference: str | None
    primary_brand_color: str | None


class WidgetAssistantRead(DomainSchema):
    display_name: str
    greeting: str
    avatar_reference: str | None
    primary_color: str | None


class WidgetLocationRead(DomainSchema):
    id: UUID
    display_name: str


class WidgetComplianceRead(DomainSchema):
    requires_age_gate: bool
    website_attestation_notice: str


class WidgetBootstrapRead(DomainSchema):
    business: WidgetBusinessRead
    assistant: WidgetAssistantRead
    locations: list[WidgetLocationRead]
    compliance: WidgetComplianceRead
