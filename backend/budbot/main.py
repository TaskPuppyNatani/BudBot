"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import httpx

from budbot.api.errors import install_exception_handlers
from budbot.api.routes.assistants import router as assistants_router
from budbot.api.routes.businesses import router as businesses_router
from budbot.api.routes.compliance import router as compliance_router
from budbot.api.routes.commands import router as commands_router
from budbot.api.routes.chat import router as chat_router
from budbot.api.routes.health import router as health_router
from budbot.api.routes.locations import router as locations_router
from budbot.api.routes.sessions import router as sessions_router
from budbot.core.config import Settings, get_settings
from budbot.database.session import Database
from budbot.providers.ai.harness_registry import build_ai_harness_registry
from budbot.providers.ai.registry import build_ai_provider_registry


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with lifespan-owned runtime resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_settings = settings or get_settings()
        database = Database(active_settings)
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=active_settings.ai_timeout_seconds,
                connect=min(
                    active_settings.ai_connect_timeout_seconds,
                    active_settings.ai_timeout_seconds,
                ),
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        app.state.settings = active_settings
        app.state.database = database
        app.state.ai_http_client = http_client
        app.state.ai_provider_registry = build_ai_provider_registry(http_client)
        app.state.ai_harness_registry = build_ai_harness_registry()
        try:
            yield
        finally:
            await http_client.aclose()
            await database.dispose()

    application = FastAPI(
        title="BudBot API",
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(businesses_router)
    application.include_router(locations_router)
    application.include_router(assistants_router)
    application.include_router(compliance_router)
    application.include_router(sessions_router)
    application.include_router(commands_router)
    application.include_router(chat_router)
    return application


app = create_app()
