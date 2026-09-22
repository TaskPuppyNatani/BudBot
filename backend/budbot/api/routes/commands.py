"""Bounded customer command execution and autocomplete metadata API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.commands.bootstrap import build_command_executor
from budbot.commands.types import CommandExecutionContext, CommandScope
from budbot.core.tenancy import TenantContext
from budbot.schemas.commands import (
    CommandExecuteRead,
    CommandExecuteRequest,
    CommandMetadataRead,
)


router = APIRouter(prefix="/api/v1/commands", tags=["commands"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


def _context(
    session: AsyncSession,
    tenant: TenantContext,
    customer_session_id: UUID,
) -> CommandExecutionContext:
    return CommandExecutionContext(
        session=session,
        tenant=tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=customer_session_id,
    )


@router.post("/execute", response_model=CommandExecuteRead)
async def execute_customer_command(
    payload: CommandExecuteRequest,
    session: Session,
    tenant: Tenant,
) -> CommandExecuteRead:
    result = await build_command_executor().execute(
        payload.input,
        _context(session, tenant, payload.session_id),
    )
    return CommandExecuteRead(
        canonical_name=result.canonical_name,
        requested_name=result.requested_name,
        output=result.output,
        commands=[CommandMetadataRead.model_validate(value) for value in result.commands],
    )


@router.get("", response_model=list[CommandMetadataRead])
async def list_customer_commands(
    session_id: Annotated[UUID, Query()],
    session: Session,
    tenant: Tenant,
) -> list[CommandMetadataRead]:
    commands = await build_command_executor().metadata(
        _context(session, tenant, session_id)
    )
    return [CommandMetadataRead.model_validate(value) for value in commands]
