"""Owner-facing business team and invitation contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from budbot.schemas.common import DomainSchema

TeamRole = Literal["owner", "admin", "manager", "viewer"]


class InvitationCreate(DomainSchema):
    email: str = Field(min_length=3, max_length=320)
    role: TeamRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if "@" not in normalized or any(character.isspace() for character in normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class MembershipRoleUpdate(DomainSchema):
    role: TeamRole


class MemberRead(DomainSchema):
    membership_id: UUID
    user_id: UUID
    display_name: str | None
    email: str
    role: str
    active: bool
    created_at: datetime


class PendingInvitationRead(DomainSchema):
    invitation_id: UUID
    email: str
    role: TeamRole
    created_at: datetime
    expires_at: datetime


class TeamRead(DomainSchema):
    members: list[MemberRead]
    invitations: list[PendingInvitationRead]


class InvitationCreated(DomainSchema):
    invitation_id: UUID
    email: str
    role: TeamRole
    expires_at: datetime
    token: str


class InvitationTokenRequest(DomainSchema):
    token: str = Field(min_length=20, max_length=128)


class InvitationPreview(DomainSchema):
    email: str
    business_name: str
    role: TeamRole
    expires_at: datetime


class NewAccountInvitationAccept(InvitationTokenRequest):
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class InvitationAccepted(DomainSchema):
    message: str
