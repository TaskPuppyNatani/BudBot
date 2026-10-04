"""Authenticated uploads and narrowly published customer branding images."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.schemas.branding import BrandingUpdate, MAX_ENCODED_IMAGE_CHARS
from budbot.services.branding_service import save_branding
from budbot.services.local_asset_service import LocalAssetError, LocalAssetStore

router = APIRouter(tags=["branding"])
Session = Annotated[AsyncSession, Depends(get_session)]
WriteAccess = Annotated[
    AdminAccess, Depends(require_business_permission("branding.write", csrf=True))
]
# Two bounded encoded images plus bounded textual configuration/JSON overhead.
MAX_BRANDING_REQUEST_BYTES = 2 * MAX_ENCODED_IMAGE_CHARS + 32_768


@router.put("/api/v1/businesses/{business_id}/branding")
async def update_branding(
    business_id: UUID, request: Request, session: Session, access: WriteAccess
) -> dict[str, dict[str, object]]:
    """Authenticate before reading a bounded JSON body; no multipart dependency."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BRANDING_REQUEST_BYTES:
            raise HTTPException(413, "Branding upload is too large. Use images up to 4 MB each.")
        body.extend(chunk)
    try:
        payload = BrandingUpdate.model_validate(json.loads(body))
    except (ValueError, UnicodeError, ValidationError):
        # Do not echo base64, paths, or other submitted values.
        raise HTTPException(422, "Invalid branding update. Check image size and branding fields.") from None
    return await save_branding(
        session, access.tenant, business_id, payload, access.user_id,
        request.app.state.settings.local_assets_dir, published=True,
    )


@router.get("/assets/branding/{business_id}/{filename}")
async def published_branding_image(
    business_id: UUID, filename: str, request: Request, session: Session
) -> Response:
    """Only the active business's currently referenced logo/avatar is public."""
    pair = (await session.execute(
        select(Business.logo_reference, AssistantConfiguration.avatar_reference)
        .join(AssistantConfiguration, AssistantConfiguration.business_id == Business.id)
        .where(Business.id == business_id, Business.active.is_(True))
    )).first()
    candidates = {
        f"/local-assets/{business_id}/{filename}",
        f"/assets/branding/{business_id}/{filename}",
    }
    if pair is None or not candidates.intersection(pair):
        raise HTTPException(404, "Image not found.")
    try:
        content = LocalAssetStore(request.app.state.settings.local_assets_dir).read_published(
            business_id, filename
        )
    except LocalAssetError:
        raise HTTPException(404, "Image not found.") from None
    media_type = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[filename.rsplit(".", 1)[-1]]
    return Response(content, media_type=media_type, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
