"""Loopback-only branding controls for the local M8 operator experience."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.schemas.assistant import AssistantRead, AssistantUpdate
from budbot.schemas.business import BusinessRead, BusinessUpdate
from budbot.schemas.common import DomainSchema, HexColor, Name, ShortText
from budbot.services.assistant_service import AssistantService
from budbot.services.business_service import BusinessService
from budbot.services.local_asset_service import (
    MAX_IMAGE_BYTES,
    LocalAssetError,
    LocalAssetStore,
)

router = APIRouter(prefix="/api/v1/local", tags=["local development branding"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
MAX_ENCODED_IMAGE_CHARS = ((MAX_IMAGE_BYTES + 2) // 3) * 4
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LocalBusinessChoice(DomainSchema):
    id: UUID
    display_name: str
    logo_reference: str | None


class EncodedImage(DomainSchema):
    content_base64: str = Field(min_length=4, max_length=MAX_ENCODED_IMAGE_CHARS)


class LocalBrandingUpdate(DomainSchema):
    display_name: Name | None = None
    assistant_display_name: Name | None = None
    greeting: ShortText | None = None
    primary_brand_color: HexColor | None = None
    business_logo: EncodedImage | None = None
    assistant_avatar: EncodedImage | None = None
    remove_business_logo: bool = False
    remove_assistant_avatar: bool = False

    @model_validator(mode="after")
    def validate_asset_actions(self) -> "LocalBrandingUpdate":
        if self.business_logo is not None and self.remove_business_logo:
            raise ValueError("Choose a business logo or remove it, not both.")
        if self.assistant_avatar is not None and self.remove_assistant_avatar:
            raise ValueError("Choose an assistant avatar or remove it, not both.")
        for field in ("display_name", "assistant_display_name", "greeting"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        if not self.model_fields_set:
            raise ValueError("At least one branding change must be supplied.")
        return self


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


def _decode_image(upload: EncodedImage) -> bytes:
    try:
        payload = base64.b64decode(upload.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected image could not be decoded.",
        ) from None
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Choose an image no larger than 4 MB.",
        )
    return payload


@router.get("/businesses", response_model=list[LocalBusinessChoice])
async def list_local_businesses(
    request: Request,
    session: Session,
) -> list[Business]:
    """List active local tenants for the Control Center's business switcher."""

    require_local_development(request)
    result = await session.scalars(
        select(Business)
        .where(Business.active.is_(True))
        .order_by(Business.display_name, Business.id)
        .limit(200)
    )
    return list(result.all())


@router.get("/businesses/{business_id}/assets/{filename}/preview")
async def render_local_asset_preview(
    business_id: UUID,
    filename: str,
    request: Request,
    tenant: Tenant,
) -> Response:
    """Render an in-memory PNG for the Tk Control Center without storing a copy."""

    require_local_development(request)
    tenant.require_business(business_id)
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
    tenant: Tenant,
) -> dict[str, dict[str, object]]:
    """Persist one tenant's supported customer-brand fields and local image assets."""

    require_local_development(request)
    tenant.require_business(business_id)
    business_service = BusinessService(session)
    assistant_service = AssistantService(session, tenant)
    business = await business_service.get(tenant, business_id)
    assistant = await assistant_service.get(business_id)
    store = LocalAssetStore(request.app.state.settings.local_assets_dir)
    created_references: list[str] = []
    old_references = {business.logo_reference, assistant.avatar_reference} - {None}

    async def store_image(upload: EncodedImage) -> str:
        try:
            reference, _path = store.save(business_id, _decode_image(upload))
        except LocalAssetError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from None
        created_references.append(reference)
        return reference

    try:
        business_changes: dict[str, object] = {}
        if "display_name" in payload.model_fields_set:
            business_changes["display_name"] = payload.display_name
        if "primary_brand_color" in payload.model_fields_set:
            business_changes["primary_brand_color"] = payload.primary_brand_color
        if payload.business_logo is not None:
            business_changes["logo_reference"] = await store_image(payload.business_logo)
        elif payload.remove_business_logo:
            business_changes["logo_reference"] = None

        assistant_changes: dict[str, object] = {}
        if "assistant_display_name" in payload.model_fields_set:
            assistant_changes["display_name"] = payload.assistant_display_name
        if "greeting" in payload.model_fields_set:
            assistant_changes["greeting"] = payload.greeting
        if payload.assistant_avatar is not None:
            assistant_changes["avatar_reference"] = await store_image(
                payload.assistant_avatar
            )
        elif payload.remove_assistant_avatar:
            assistant_changes["avatar_reference"] = None
        if business_changes:
            business = await business_service.update(
                tenant, business_id, BusinessUpdate(**business_changes)
            )
        if assistant_changes:
            assistant = await assistant_service.update(
                business_id, AssistantUpdate(**assistant_changes)
            )
        await session.commit()
    except Exception:
        await session.rollback()
        for reference in created_references:
            store.remove(business_id, reference)
        raise

    new_references = {business.logo_reference, assistant.avatar_reference} - {None}
    for reference in old_references - new_references:
        try:
            store.remove(business_id, reference)
        except OSError:
            # A stale local file is harmless; a saved database reference is authoritative.
            pass

    return {
        "business": BusinessRead.model_validate(business).model_dump(mode="json"),
        "assistant": AssistantRead.model_validate(assistant).model_dump(mode="json"),
    }
