"""FastAPI dependencies for application-owned resources."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.tenancy import TenantContext
from budbot.database.session import Database
from budbot.providers.ai.harness_registry import AIHarnessRegistry
from budbot.providers.ai.registry import AIProviderRegistry


async def get_database(request: Request) -> Database:
    """Return the database owned by the current application lifespan."""

    return request.app.state.database


async def get_ai_provider_registry(request: Request) -> AIProviderRegistry:
    """Return transports that share the application-lifecycle HTTP client."""

    return request.app.state.ai_provider_registry


async def get_ai_harness_registry(request: Request) -> AIHarnessRegistry:
    """Return the explicit trusted model/harness adapter registry."""

    return request.app.state.ai_harness_registry


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a request transaction that commits only after successful handling."""

    database = await get_database(request)
    async for session in database.session():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_context(
    tenant_business_id: Annotated[
        UUID,
        Header(
            alias="X-BudBot-Business-ID",
            description="Temporary M2 development tenant context; not authentication",
        ),
    ],
) -> TenantContext:
    """Resolve the explicit temporary pre-authentication tenant header."""

    return TenantContext(business_id=tenant_business_id)
