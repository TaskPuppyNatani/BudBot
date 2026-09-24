"""Minimal provider-neutral chat API for the M7 orchestration layer."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import (
    get_ai_harness_registry,
    get_ai_provider_registry,
    get_session,
    get_tenant_context,
)
from budbot.core.tenancy import TenantContext
from budbot.providers.ai.harness_registry import AIHarnessRegistry
from budbot.providers.ai.registry import AIProviderRegistry
from budbot.schemas.chat import ChatRequest, ChatResponse
from budbot.services.chat_service import AIService


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
ProviderRegistry = Annotated[AIProviderRegistry, Depends(get_ai_provider_registry)]
HarnessRegistry = Annotated[AIHarnessRegistry, Depends(get_ai_harness_registry)]


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    session: Session,
    tenant: Tenant,
    providers: ProviderRegistry,
    harnesses: HarnessRegistry,
) -> ChatResponse:
    service = AIService(
        session,
        tenant,
        request.app.state.settings,
        providers,
        harnesses,
    )
    result = await service.chat(payload.session_id, payload.message)
    return ChatResponse(content=result.content or "")
