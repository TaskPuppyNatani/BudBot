"""Application package and lifecycle smoke tests."""

from fastapi import FastAPI

from budbot.core.config import Settings
from budbot.main import app, create_app


def test_module_exposes_fastapi_application() -> None:
    assert isinstance(app, FastAPI)


async def test_application_lifespan_sets_runtime_resources(settings: Settings) -> None:
    application = create_app(settings)

    async with application.router.lifespan_context(application):
        assert application.state.settings is settings
        assert application.state.database is not None
