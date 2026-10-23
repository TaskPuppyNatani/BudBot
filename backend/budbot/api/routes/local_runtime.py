"""Development-only owner/CSRF gateway to the host's narrow Unix socket."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.services.audit_service import record_audit_event
from budbot.services.local_runtime_service import LocalRuntimeService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/local-runtime", tags=["local runtime"])
Session = Annotated[AsyncSession, Depends(get_session)]
Read = Annotated[AdminAccess, Depends(require_business_permission("runtime.shutdown"))]
Write = Annotated[AdminAccess, Depends(require_business_permission("runtime.shutdown", csrf=True))]


class ShutdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def local_only(request: Request) -> None:
    if request.app.state.settings.environment != "development" or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(404, "Not found.")
    origin = request.headers.get("origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "A same-origin local request is required.")


@router.get("")
async def runtime_status(business_id: UUID, access: Read, request: Request):
    local_only(request)
    return await LocalRuntimeService().status()


@router.post("/shutdown", status_code=202)
async def shutdown(
    business_id: UUID, access: Write, request: Request, session: Session,
    payload: Annotated[ShutdownRequest, Body()] = ShutdownRequest(),
):
    local_only(request)
    # Commit the attempted action before signaling a process that will stop us.
    await record_audit_event(session, "admin.local_runtime.shutdown_requested",
        actor_user_id=access.user_id, business_id=access.business_id,
        resource_type="local_runtime", resource_id=access.business_id)
    await session.commit()
    await LocalRuntimeService().shutdown()
    return {"state": "stopping"}
