"""Shared authenticated branding mutation with rollback-safe image cleanup."""

import base64
import binascii
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from budbot.core.tenancy import TenantContext
from budbot.schemas.branding import BrandingUpdate, EncodedImage
from budbot.schemas.assistant import AssistantRead, AssistantUpdate
from budbot.schemas.business import BusinessRead, BusinessUpdate
from budbot.services.assistant_service import AssistantService
from budbot.services.audit_service import record_audit_event
from budbot.services.business_service import BusinessService
from budbot.services.local_asset_service import MAX_IMAGE_BYTES, LocalAssetError, LocalAssetStore


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


async def save_branding(
    session: AsyncSession, tenant: TenantContext, business_id: UUID,
    payload: BrandingUpdate, actor_user_id: UUID, assets_dir: Path,
    *, published: bool = False,
) -> dict[str, dict[str, object]]:
    tenant.require_business(business_id)
    business_service = BusinessService(session)
    assistant_service = AssistantService(session, tenant)
    business = await business_service.get(tenant, business_id)
    assistant = await assistant_service.get(business_id)
    store = LocalAssetStore(assets_dir)
    created_references: list[str] = []
    old_references = {business.logo_reference, assistant.avatar_reference} - {None}

    async def store_image(upload: EncodedImage) -> str:
        try:
            reference, _path = store.save(business_id, _decode_image(upload))
        except LocalAssetError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from None
        if published:
            reference = reference.replace("/local-assets/", "/assets/branding/", 1)
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
        await record_audit_event(
            session,
            "admin.branding.saved",
            actor_user_id=actor_user_id,
            business_id=business_id,
            resource_type="branding",
            resource_id=business_id,
            details={"changed_fields": ",".join(sorted(payload.model_fields_set))},
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
