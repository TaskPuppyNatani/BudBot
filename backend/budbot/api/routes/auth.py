"""First-party login and server-side administrative session lifecycle."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import (
    ADMIN_SESSION_COOKIE,
    AdminPrincipal,
    get_current_admin,
    get_session,
    list_authorized_businesses,
    require_csrf,
)
from budbot.core.config import Settings
from budbot.core.permissions import AdminPermission, permissions_for_role
from budbot.core.security import new_opaque_token, token_digest
from budbot.models.auth import AdminSession
from budbot.models.user import UserAccount
from budbot.schemas.auth import (
    AdminBusinessMembershipRead,
    AdminSessionRead,
    AdminUserRead,
    LoginRequest,
)
from budbot.services.audit_service import record_audit_event
from budbot.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
Session = Annotated[AsyncSession, Depends(get_session)]
Principal = Annotated[AdminPrincipal, Depends(get_current_admin)]


async def _session_read(
    session: AsyncSession,
    user: UserAccount,
    csrf_token: str,
) -> AdminSessionRead:
    businesses = await list_authorized_businesses(
        session, user.id, AdminPermission.BUSINESS_READ.value
    )
    return AdminSessionRead(
        csrf_token=csrf_token,
        user=AdminUserRead(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
        ),
        businesses=[
            AdminBusinessMembershipRead(
                business_id=business.id,
                display_name=business.display_name,
                role=membership.role,
                permissions=sorted(permissions_for_role(membership.role)),
            )
            for business, membership in businesses
        ],
    )


@router.post("/login", response_model=None)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session,
) -> AdminSessionRead | dict[str, str]:
    """Authenticate without distinguishing unknown, inactive, or wrong passwords."""

    client_host = request.client.host if request.client is not None else "unknown"
    issued = await AuthService(session, request.app.state.settings).authenticate(
        payload.email, payload.password, client_host
    )
    response.headers["Cache-Control"] = "no-store"
    if issued is None:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"detail": "Invalid email or password."}

    result = await _session_read(session, issued.user, issued.csrf_token)
    # Request-scope dependency cleanup can run after response delivery. Publish
    # the cookie/token only after its session, CSRF digest and audit are committed.
    await session.commit()
    settings: Settings = request.app.state.settings
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=issued.token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path="/",
    )
    return result


@router.get("/me", response_model=AdminSessionRead)
async def current_admin(
    response: Response,
    session: Session,
    principal: Principal,
) -> AdminSessionRead:
    response.headers["Cache-Control"] = "no-store"
    admin_session = await session.get(AdminSession, principal.session_id)
    user = await session.get(UserAccount, principal.user_id)
    if admin_session is None or user is None:
        # The principal dependency already validates both; this covers a
        # concurrent revocation/deactivation between checks.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )
    csrf_token = new_opaque_token()
    admin_session.csrf_digest = token_digest(csrf_token)
    result = await _session_read(session, user, csrf_token)
    # An immediately following unsafe request must see this digest. Construct the
    # validated response first so failed application work still rolls back.
    await session.commit()
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    request: Request,
    response: Response,
    session: Session,
    principal: Principal,
) -> Response:
    require_csrf(request, principal)
    await AuthService(session, request.app.state.settings).revoke_session(
        principal.session_id, principal.user_id
    )
    await record_audit_event(
        session,
        "auth.logout",
        actor_user_id=principal.user_id,
        resource_type="admin_session",
        resource_id=principal.session_id,
    )
    settings: Settings = request.app.state.settings
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def logout_all(
    request: Request,
    response: Response,
    session: Session,
    principal: Principal,
) -> Response:
    require_csrf(request, principal)
    revoked = await AuthService(session, request.app.state.settings).revoke_all_sessions(
        principal.user_id
    )
    await record_audit_event(
        session,
        "auth.logout_all",
        actor_user_id=principal.user_id,
        details={"revoked_session_count": revoked},
    )
    settings: Settings = request.app.state.settings
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
