"""Application package and lifecycle smoke tests."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient

from budbot.core.config import Settings
from budbot.main import app, create_app


def test_module_exposes_fastapi_application() -> None:
    assert isinstance(app, FastAPI)


def test_widget_assets_are_mounted_for_same_origin_embedding() -> None:
    widget_mount = next(
        route for route in app.routes if getattr(route, "path", None) == "/widget"
    )
    assert isinstance(widget_mount.app, StaticFiles)
    assert (widget_mount.app.directory / "src" / "embed.js").is_file()


async def test_local_widget_preview_is_served() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://budbot.test"
    ) as client:
        response = await client.get("/widget/")
        embed_script = await client.get("/widget/src/embed.js")
    assert response.status_code == 200
    assert "BudBot customer widget preview" in response.text
    assert "No business UUID entry is needed" in response.text
    assert embed_script.status_code == 200
    assert "class BudBotWidget" in embed_script.text


async def test_application_lifespan_sets_runtime_resources(settings: Settings) -> None:
    application = create_app(settings)

    async with application.router.lifespan_context(application):
        assert application.state.settings is settings
        assert application.state.database is not None
