"""Administrative authentication request and response contracts."""

from uuid import UUID

from pydantic import Field, field_validator

from budbot.schemas.common import DomainSchema


class LoginRequest(DomainSchema):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if "@" not in normalized or any(character.isspace() for character in normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class AdminBusinessMembershipRead(DomainSchema):
    business_id: UUID
    display_name: str
    role: str


class AdminUserRead(DomainSchema):
    id: UUID
    email: str
    display_name: str | None


class AdminSessionRead(DomainSchema):
    csrf_token: str
    user: AdminUserRead
    businesses: list[AdminBusinessMembershipRead]
