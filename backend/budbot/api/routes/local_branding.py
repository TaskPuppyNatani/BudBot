"""Loopback-only branding controls for the local M8 operator experience."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import (
    AdminAccess,
    AdminPrincipal,
    get_current_admin,
    get_session,
    list_authorized_businesses,
    require_business_permission,
)
from budbot.core.permissions import AdminPermission
from budbot.models.business import Business
from budbot.schemas.common import DomainSchema
from budbot.schemas.branding import BrandingUpdate as LocalBrandingUpdate
from budbot.services.branding_service import save_branding
from budbot.services.local_asset_service import (
    LocalAssetError,
    LocalAssetStore,
)

router = APIRouter(prefix="/api/v1/local", tags=["local development branding"])
Session = Annotated[AsyncSession, Depends(get_session)]
Principal = Annotated[AdminPrincipal, Depends(get_current_admin)]
ReadAccess = Annotated[
    AdminAccess, Depends(require_business_permission("branding.read"))
]
WriteAccess = Annotated[
    AdminAccess,
    Depends(require_business_permission("branding.write", csrf=True)),
]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LocalBusinessChoice(DomainSchema):
    id: UUID
    display_name: str
    logo_reference: str | None



def require_local_development(request: Request) -> None:
    """Keep mutation and tenant-listing routes out of production and off LAN hosts."""

    if request.app.state.settings.environment != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    host = urlsplit(f"//{request.headers.get('host', '')}").hostname
    if (host or "").lower() not in LOCAL_HOSTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    origin = request.headers.get("origin")
    if origin:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or (parsed_origin.hostname or "").lower() not in LOCAL_HOSTS
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


@router.get("/businesses", response_model=list[LocalBusinessChoice])
async def list_local_businesses(
    request: Request,
    session: Session,
    principal: Principal,
) -> list[Business]:
    """List only active tenants covered by the signed-in user's membership."""

    require_local_development(request)
    authorized = await list_authorized_businesses(
        session, principal.user_id, AdminPermission.BRANDING_READ.value
    )
    return [business for business, _membership in authorized[:200]]


@router.get("/businesses/{business_id}/assets/{filename}/preview")
async def render_local_asset_preview(
    business_id: UUID,
    filename: str,
    request: Request,
    access: ReadAccess,
) -> Response:
    """Render an in-memory PNG for the Tk Control Center without storing a copy."""

    require_local_development(request)
    access.tenant.require_business(business_id)
    store = LocalAssetStore(request.app.state.settings.local_assets_dir)
    reference = f"/local-assets/{business_id}/{filename}"
    try:
        preview = store.render_preview(business_id, reference)
    except LocalAssetError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This local image preview is unavailable.",
        ) from None
    return Response(
        content=preview,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.put("/businesses/{business_id}/branding")
async def save_local_branding(
    business_id: UUID,
    payload: LocalBrandingUpdate,
    request: Request,
    session: Session,
    access: WriteAccess,
) -> dict[str, dict[str, object]]:
    """Persist one tenant's supported customer-brand fields and local image assets."""

    require_local_development(request)
    return await save_branding(
        session, access.tenant, business_id, payload, access.user_id,
        request.app.state.settings.local_assets_dir,
    )
