"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from budbot.api.errors import install_exception_handlers
from budbot.api.routes.assistants import router as assistants_router
from budbot.api.routes.businesses import router as businesses_router
from budbot.api.routes.compliance import router as compliance_router
from budbot.api.routes.health import router as health_router
from budbot.api.routes.locations import router as locations_router
from budbot.api.routes.sessions import router as sessions_router
from budbot.core.config import Settings, get_settings
from budbot.database.session import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with lifespan-owned runtime resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_settings = settings or get_settings()
        database = Database(active_settings)
        app.state.settings = active_settings
        app.state.database = database
        try:
            yield
        finally:
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
    return application


app = create_app()
