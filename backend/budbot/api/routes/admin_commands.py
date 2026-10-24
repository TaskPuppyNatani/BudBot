"""Cookie/CSRF-authenticated admin transport; customer commands stay separate."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.commands.bootstrap import ADMIN_HELP_PERMISSION, build_command_executor
from budbot.commands.types import AdminCommandRuntime, CommandExecutionContext, CommandScope, PermissionContext
from budbot.core.exceptions import CommandError, DomainError
from budbot.core.permissions import permissions_for_role
from budbot.schemas.commands import AdminCommandExecuteRead, AdminCommandExecuteRequest, CommandMetadataRead
from budbot.services.location_service import LocationService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/commands", tags=["admin commands"])
Session = Annotated[AsyncSession, Depends(get_session)]
Read = Annotated[AdminAccess, Depends(require_business_permission("business.read"))]
Execute = Annotated[AdminAccess, Depends(require_business_permission("business.read", csrf=True))]


async def _context(session, access, request, location_id=None):
    if location_id is not None:
        await LocationService(session, access.tenant).get(location_id)
    return CommandExecutionContext(
        session=session, tenant=access.tenant, scope=CommandScope.ADMIN,
        permission_context=PermissionContext(authenticated_admin=True,
            permissions=permissions_for_role(access.role) | {ADMIN_HELP_PERMISSION}),
        admin_runtime=AdminCommandRuntime(access.user_id, location_id,
            request.app.state.settings, request.app.state.ai_provider_registry,
            request.app.state.ai_harness_registry),
    )


@router.get("", response_model=list[CommandMetadataRead])
async def list_admin_commands(business_id: UUID, session: Session, access: Read, request: Request):
    commands = await build_command_executor().metadata(await _context(session, access, request))
    return [CommandMetadataRead.model_validate(item) for item in commands]


@router.post("/execute", response_model=AdminCommandExecuteRead)
async def execute_admin_command(business_id: UUID, payload: AdminCommandExecuteRequest,
    session: Session, access: Execute, request: Request):
    try:
        result = await build_command_executor().execute(payload.input,
            await _context(session, access, request, payload.location_id))
        response = AdminCommandExecuteRead(canonical_name=result.canonical_name,
            requested_name=result.requested_name, output=result.output,
            commands=[CommandMetadataRead.model_validate(item) for item in result.commands],
            location_id=result.selected_location_id if result.canonical_name == "location" else payload.location_id,
            preview_url=result.preview_url)
        # Publish completed state and its existing audit records before reloads.
        await session.commit()
        return response
    except DomainError:
        raise
    except Exception:
        await session.rollback()
        # Never expose command input, service exceptions, provider bodies or keys.
        raise CommandError("COMMAND_FAILED",
            "The admin command could not be completed. Reload settings before retrying; check the backend if it persists.",
            status_code=500) from None
