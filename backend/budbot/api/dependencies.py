"""FastAPI dependencies for application-owned resources."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.permissions import role_allows
from budbot.core.security import token_digest
from budbot.core.tenancy import TenantContext
from budbot.core.time import ensure_utc, utc_now
from budbot.models.auth import AdminSession
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from budbot.database.session import Database
from budbot.providers.ai.harness_registry import AIHarnessRegistry
from budbot.providers.ai.registry import AIProviderRegistry

ADMIN_SESSION_COOKIE = "budbot_admin_session"
CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    user_id: UUID
    session_id: UUID
    csrf_digest: str


@dataclass(frozen=True, slots=True)
class AdminAccess:
    user_id: UUID
    session_id: UUID
    business_id: UUID
    role: str
    tenant: TenantContext


def require_csrf(request: Request, principal: AdminPrincipal) -> None:
    candidate = request.headers.get(CSRF_HEADER, "")
    if not candidate or not hmac.compare_digest(
        token_digest(candidate), principal.csrf_digest
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid CSRF token is required for this request.",
        )


async def get_database(request: Request) -> Database:
    """Return the database owned by the current application lifespan."""

    return request.app.state.database


async def get_ai_provider_registry(request: Request) -> AIProviderRegistry:
    """Return transports that share the application-lifecycle HTTP client."""

    return request.app.state.ai_provider_registry


async def get_ai_harness_registry(request: Request) -> AIHarnessRegistry:
    """Return the explicit trusted model/harness adapter registry."""

    return request.app.state.ai_harness_registry


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a request transaction that commits only after successful handling."""

    database = await get_database(request)
    async for session in database.session():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_admin(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPrincipal:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )
    result = await session.execute(
        select(AdminSession, UserAccount)
        .join(UserAccount, UserAccount.id == AdminSession.user_id)
        .where(
            AdminSession.token_digest == token_digest(token),
            AdminSession.revoked_at.is_(None),
            UserAccount.active.is_(True),
        )
    )
    pair = result.first()
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )
    admin_session, user = pair
    if ensure_utc(admin_session.expires_at) <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )
    return AdminPrincipal(
        user_id=user.id,
        session_id=admin_session.id,
        csrf_digest=admin_session.csrf_digest,
    )


def require_business_permission(
    permission: str,
    *,
    csrf: bool = False,
):
    """Resolve a path business only after active membership and role checks."""

    async def dependency(
        business_id: UUID,
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
        principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
    ) -> AdminAccess:
        if csrf:
            require_csrf(request, principal)
        result = await session.execute(
            select(BusinessMembership, Business)
            .join(Business, Business.id == BusinessMembership.business_id)
            .where(
                BusinessMembership.user_id == principal.user_id,
                BusinessMembership.business_id == business_id,
                Business.active.is_(True),
            )
        )
        pair = result.first()
        if pair is None:
            # Keep unknown, inactive, and unowned business IDs indistinguishable.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Business not found.",
            )
        membership, _business = pair
        if not role_allows(membership.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return AdminAccess(
            user_id=principal.user_id,
            session_id=principal.session_id,
            business_id=business_id,
            role=membership.role,
            tenant=TenantContext(business_id=business_id),
        )

    return dependency


async def require_business_creator(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AdminPrincipal:
    require_csrf(request, principal)
    owner_business = await session.scalar(
        select(BusinessMembership.id)
        .join(Business, Business.id == BusinessMembership.business_id)
        .where(
            BusinessMembership.user_id == principal.user_id,
            BusinessMembership.role == "owner",
            Business.active.is_(True),
        )
        .limit(1)
    )
    if owner_business is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active business owner account is required.",
        )
    return principal


async def list_authorized_businesses(
    session: AsyncSession, user_id: UUID, permission: str
) -> list[tuple[Business, BusinessMembership]]:
    result = await session.execute(
        select(Business, BusinessMembership)
        .join(BusinessMembership, BusinessMembership.business_id == Business.id)
        .where(
            BusinessMembership.user_id == user_id,
            Business.active.is_(True),
        )
        .order_by(Business.display_name, Business.id)
    )
    return [
        (business, membership)
        for business, membership in result.all()
        if role_allows(membership.role, permission)
    ]


async def get_tenant_context(
    tenant_business_id: Annotated[
        UUID,
        Header(
            alias="X-BudBot-Business-ID",
            description="Temporary M2 development tenant context; not authentication",
        ),
    ],
) -> TenantContext:
    """Resolve the explicit temporary pre-authentication tenant header."""

    return TenantContext(business_id=tenant_business_id)
