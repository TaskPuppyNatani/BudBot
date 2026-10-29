"""Owner-only tenant team management and bearer-link invitation acceptance."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import (
    AdminAccess,
    AdminPrincipal,
    get_current_admin,
    get_session,
    require_business_permission,
    require_csrf,
)
from budbot.core.config import Settings
from budbot.schemas.team import (
    InvitationAccepted,
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationTokenRequest,
    MembershipRoleUpdate,
    NewAccountInvitationAccept,
    TeamRead,
)
from budbot.services.team_service import TeamService

router = APIRouter(tags=["team"])
Session = Annotated[AsyncSession, Depends(get_session)]
TeamReadAccess = Annotated[AdminAccess, Depends(require_business_permission("membership.manage"))]
TeamWriteAccess = Annotated[AdminAccess, Depends(require_business_permission("membership.manage", csrf=True))]


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    site = request.headers.get("sec-fetch-site")
    if origin != expected or site == "cross-site":
        raise HTTPException(status_code=403, detail="This invitation request must come from BudBot.")


def _peer_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/api/v1/businesses/{business_id}/members", response_model=TeamRead)
async def list_team(business_id: UUID, session: Session, access: TeamReadAccess) -> object:
    return await TeamService(session).list_team(business_id)


@router.post(
    "/api/v1/businesses/{business_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    business_id: UUID,
    payload: InvitationCreate,
    request: Request,
    session: Session,
    access: TeamWriteAccess,
) -> InvitationCreated:
    invitation, token = await TeamService(session, _settings(request)).create_invitation(
        business_id, access.user_id, payload.email, payload.role
    )
    return InvitationCreated(
        invitation_id=invitation.id,
        email=invitation.recipient_email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        token=token,
    )


@router.delete("/api/v1/businesses/{business_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    business_id: UUID,
    invitation_id: UUID,
    session: Session,
    access: TeamWriteAccess,
) -> None:
    await TeamService(session).revoke_invitation(business_id, access.user_id, invitation_id)


@router.patch("/api/v1/businesses/{business_id}/members/{membership_id}", status_code=204)
async def change_member_role(
    business_id: UUID,
    membership_id: UUID,
    payload: MembershipRoleUpdate,
    session: Session,
    access: TeamWriteAccess,
) -> None:
    await TeamService(session).change_role(
        business_id, access.user_id, membership_id, payload.role
    )


@router.delete("/api/v1/businesses/{business_id}/members/{membership_id}", status_code=204)
async def remove_member(
    business_id: UUID,
    membership_id: UUID,
    session: Session,
    access: TeamWriteAccess,
) -> None:
    await TeamService(session).remove_member(business_id, access.user_id, membership_id)


@router.post("/api/v1/invitations/inspect", response_model=InvitationPreview)
async def inspect_invitation(
    payload: InvitationTokenRequest, request: Request, session: Session,
) -> InvitationPreview:
    _require_same_origin(request)
    service = TeamService(session, _settings(request))
    await service.check_public_attempt_limit(_peer_ip(request))
    return await service.inspect_invitation(payload.token)


@router.post("/api/v1/invitations/accept/new", response_model=InvitationAccepted)
async def accept_new_account(
    payload: NewAccountInvitationAccept,
    request: Request,
    session: Session,
) -> InvitationAccepted:
    _require_same_origin(request)
    await TeamService(session, _settings(request)).accept_new_account(
        payload.token, payload.display_name, payload.password, _peer_ip(request)
    )
    return InvitationAccepted(message="Your account is ready. Sign in to BudBot to continue.")


@router.post("/api/v1/invitations/accept", status_code=204)
async def accept_existing_account(
    payload: InvitationTokenRequest,
    request: Request,
    session: Session,
    principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> None:
    _require_same_origin(request)
    require_csrf(request, principal)
    await TeamService(session, _settings(request)).accept_existing_account(
        payload.token,
        principal.user_id,
        principal.session_id,
        request.headers.get("X-CSRF-Token", ""),
        _peer_ip(request),
    )
