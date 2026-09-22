"""M3 customer-session and website age-attestation API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.core.tenancy import TenantContext
from budbot.schemas.session import (
    AgeAttestationRequest,
    CustomerSessionCreate,
    CustomerSessionRead,
    SessionAgeGateRead,
    SessionLocationUpdate,
)
from budbot.services.session_service import SessionService

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


def _service(request: Request, session: AsyncSession, tenant: TenantContext) -> SessionService:
    return SessionService(
        session,
        tenant,
        ttl_seconds=request.app.state.settings.customer_session_ttl_seconds,
    )


@router.post("", response_model=CustomerSessionRead, status_code=status.HTTP_201_CREATED)
async def create_customer_session(
    payload: CustomerSessionCreate,
    request: Request,
    session: Session,
    tenant: Tenant,
) -> object:
    return await _service(request, session, tenant).create(payload)


@router.get("/{session_id}", response_model=CustomerSessionRead)
async def get_customer_session(
    session_id: UUID,
    request: Request,
    session: Session,
    tenant: Tenant,
) -> object:
    return await _service(request, session, tenant).get(session_id)


@router.patch("/{session_id}/location", response_model=CustomerSessionRead)
async def set_customer_session_location(
    session_id: UUID,
    payload: SessionLocationUpdate,
    request: Request,
    session: Session,
    tenant: Tenant,
) -> object:
    return await _service(request, session, tenant).set_location(session_id, payload)


@router.get("/{session_id}/age-gate", response_model=SessionAgeGateRead)
async def get_age_gate_state(
    session_id: UUID,
    request: Request,
    session: Session,
    tenant: Tenant,
) -> object:
    customer_session = await _service(request, session, tenant).get(session_id)
    return customer_session


@router.post("/{session_id}/age-attestation", response_model=CustomerSessionRead)
async def submit_age_attestation(
    session_id: UUID,
    payload: AgeAttestationRequest,
    request: Request,
    session: Session,
    tenant: Tenant,
) -> object:
    """Submit a 21+ website/session attestation, never a transaction ID check."""

    return await _service(request, session, tenant).attest(session_id, payload)
