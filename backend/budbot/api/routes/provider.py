"""Authenticated business AI configuration and write-only credentials."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.provider import ProviderRead, ProviderUpdate, CredentialUpdate, ConnectionTestRequest, ProviderConnectionRead, ProviderDiagnosticCode
from budbot.services.provider_service import ProviderService
from budbot.services.audit_service import record_audit_event

router = APIRouter(prefix="/api/v1/businesses/{business_id}/provider", tags=["provider"])
Session = Annotated[AsyncSession, Depends(get_session)]
Read = Annotated[AdminAccess, Depends(require_business_permission("provider.read"))]
Write = Annotated[AdminAccess, Depends(require_business_permission("provider.write", csrf=True))]

def service(session, access, request):
    return ProviderService(session, access.tenant, request.app.state.settings)

async def publish(session, access, svc, action):
    await record_audit_event(session, "admin.provider." + action, actor_user_id=access.user_id,
        business_id=access.business_id, resource_type="provider", resource_id=access.business_id,
        details={"provider_action": action})
    result = await svc.read()
    await session.commit()
    return result

@router.get("", response_model=ProviderRead)
async def read_provider(business_id: UUID, session: Session, access: Read, request: Request):
    return await service(session, access, request).read()

@router.put("", response_model=ProviderRead)
async def update_provider(business_id: UUID, payload: ProviderUpdate, session: Session, access: Write, request: Request):
    svc = service(session, access, request)
    await svc.update(payload)
    return await publish(session, access, svc, "configuration_updated")

@router.put("/credential", response_model=ProviderRead)
async def set_credential(business_id: UUID, payload: CredentialUpdate, session: Session, access: Write, request: Request):
    svc = service(session, access, request)
    action = await svc.set_credential(payload)
    return await publish(session, access, svc, "credential_" + action)

@router.delete("/credential", response_model=ProviderRead)
async def remove_credential(business_id: UUID, session: Session, access: Write, request: Request):
    svc = service(session, access, request)
    await svc.remove_credential()
    return await publish(session, access, svc, "credential_removed")


@router.post("/test", response_model=ProviderConnectionRead)
async def test_provider(business_id: UUID, session: Session, access: Write, request: Request,
    payload: Annotated[ConnectionTestRequest, Body()] = ConnectionTestRequest()):
    result = await service(session, access, request).test_connection(
        request.app.state.ai_provider_registry, request.app.state.ai_harness_registry)
    await record_audit_event(session, "admin.provider.connection_tested", actor_user_id=access.user_id,
        business_id=access.business_id, resource_type="provider", resource_id=access.business_id,
        details={"provider_action": "connection_tested", "provider": result.provider,
                 "success": result.code == ProviderDiagnosticCode.OK, "diagnostic_code": result.code.value})
    await session.commit()
    return result
