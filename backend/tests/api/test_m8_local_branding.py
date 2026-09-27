"""Local-only branding API, asset validation, and tenant-isolation coverage."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from io import BytesIO

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session
from budbot.core.config import Settings
from budbot.main import create_app


@pytest.fixture
async def local_branding_client(
    settings: Settings, db_session: AsyncSession, tmp_path
) -> AsyncIterator[AsyncClient]:
    local_settings = settings.model_copy(
        update={"environment": "development", "local_assets_dir": tmp_path / "assets"}
    )
    application: FastAPI = create_app(local_settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = override_session
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://127.0.0.1:8000",
        ) as client:
            yield client
    application.dependency_overrides.clear()


def _business_payload(name: str, assistant_name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "industry": "general_retail",
        "default_timezone": "America/Los_Angeles",
        "assistant": {
            "display_name": assistant_name,
            "greeting": f"Welcome to {name}",
            "fallback_message": "Please ask a team member.",
            "enabled": True,
        },
    }


async def _create_business(client: AsyncClient, name: str, assistant_name: str) -> dict[str, object]:
    response = await client.post("/api/v1/businesses", json=_business_payload(name, assistant_name))
    assert response.status_code == 201, response.text
    return response.json()


def _png(color: tuple[int, int, int, int]) -> dict[str, str]:
    stream = BytesIO()
    Image.new("RGBA", (24, 18), color).save(stream, format="PNG")
    return {"content_base64": base64.b64encode(stream.getvalue()).decode("ascii")}


def _headers(business_id: str) -> dict[str, str]:
    return {"X-BudBot-Business-ID": business_id}


@pytest.mark.asyncio
async def test_local_branding_saves_independent_logo_avatar_and_preserves_overrides(
    local_branding_client: AsyncClient,
) -> None:
    client = local_branding_client
    business = await _create_business(client, "Northwind Market", "Moss")
    business_id = str(business["id"])
    headers = _headers(business_id)

    override = await client.patch(
        f"/api/v1/businesses/{business_id}/assistant",
        headers=headers,
        json={"primary_color_override": "#2255AA"},
    )
    assert override.status_code == 200
    location_response = await client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=headers,
        json={
            "display_name": "Downtown",
            "address_line_1": "123 Main St",
            "city": "Portland",
            "region": "OR",
            "postal_code": "97201",
            "country": "us",
            "phone": "+1 (503) 555-0100",
            "timezone": "America/Los_Angeles",
            "hours": [{"day_of_week": 0, "is_closed": True}],
        },
    )
    assert location_response.status_code == 201, location_response.text
    location_id = location_response.json()["id"]
    location_override = await client.patch(
        f"/api/v1/businesses/{business_id}/locations/{location_id}/assistant-override",
        headers=headers,
        json={"display_name": "Downtown Fern", "greeting": "Hello downtown!"},
    )
    assert location_override.status_code == 200, location_override.text

    saved = await client.put(
        f"/api/v1/local/businesses/{business_id}/branding",
        headers=headers,
        json={
            "display_name": "Northwind Co-op",
            "assistant_display_name": "Fern",
            "greeting": "Welcome, neighbor!",
            "primary_brand_color": "#4ABC61",
            "business_logo": _png((20, 170, 50, 180)),
            "assistant_avatar": _png((110, 40, 210, 255)),
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["business"]["display_name"] == "Northwind Co-op"
    assert body["business"]["primary_brand_color"] == "#4ABC61"
    assert body["assistant"]["display_name"] == "Fern"
    assert body["assistant"]["greeting"] == "Welcome, neighbor!"
    assert body["assistant"]["primary_color_override"] == "#2255AA"
    effective = await client.get(
        f"/api/v1/businesses/{business_id}/locations/{location_id}/effective-assistant",
        headers=headers,
    )
    assert effective.status_code == 200
    assert effective.json()["display_name"] == "Downtown Fern"
    assert effective.json()["greeting"] == "Hello downtown!"
    assert effective.json()["primary_color"] == "#2255AA"
    logo_ref = body["business"]["logo_reference"]
    avatar_ref = body["assistant"]["avatar_reference"]
    assert logo_ref != avatar_ref
    assert (await client.get(logo_ref)).status_code == 200
    assert (await client.get(avatar_ref)).status_code == 200
    filename = logo_ref.rsplit("/", 1)[1]
    preview = await client.get(
        f"/api/v1/local/businesses/{business_id}/assets/{filename}/preview",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    with Image.open(BytesIO(preview.content)) as preview_image:
        assert preview_image.size == (24, 18)

    removed = await client.put(
        f"/api/v1/local/businesses/{business_id}/branding",
        headers=headers,
        json={"remove_business_logo": True},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["business"]["logo_reference"] is None
    assert removed.json()["assistant"]["avatar_reference"] == avatar_ref
    assert (await client.get(logo_ref)).status_code == 404
    assert (await client.get(avatar_ref)).status_code == 200
    assert (
        await client.get(
            f"/api/v1/local/businesses/{business_id}/assets/{filename}/preview",
            headers=headers,
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_local_branding_rejects_cross_tenant_and_nonlocal_requests(
    local_branding_client: AsyncClient,
) -> None:
    client = local_branding_client
    first = await _create_business(client, "First Shop", "First Helper")
    second = await _create_business(client, "Second Shop", "Second Helper")
    first_id, second_id = str(first["id"]), str(second["id"])

    cross_tenant = await client.put(
        f"/api/v1/local/businesses/{first_id}/branding",
        headers=_headers(second_id),
        json={"display_name": "Unauthorized rename"},
    )
    assert cross_tenant.status_code == 404

    foreign_preview = await client.get(
        f"/api/v1/local/businesses/{first_id}/assets/0123456789abcdef0123456789abcdef.png/preview",
        headers=_headers(second_id),
    )
    assert foreign_preview.status_code == 404

    off_host = await client.get("/api/v1/local/businesses", headers={"host": "preview.example"})
    assert off_host.status_code == 404

    listing = await client.get("/api/v1/local/businesses")
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()} == {first_id, second_id}

    deactivated = await client.patch(
        f"/api/v1/businesses/{second_id}",
        headers=_headers(second_id),
        json={"active": False},
    )
    assert deactivated.status_code == 200
    active_listing = await client.get("/api/v1/local/businesses")
    assert [item["id"] for item in active_listing.json()] == [first_id]

    cross_origin = await client.get(
        "/api/v1/local/businesses",
        headers={"origin": "https://attacker.example"},
    )
    assert cross_origin.status_code == 403


@pytest.mark.asyncio
async def test_local_branding_rejects_invalid_image_and_null_required_names(
    local_branding_client: AsyncClient,
) -> None:
    client = local_branding_client
    business = await _create_business(client, "Valid Shop", "Helpful Bot")
    business_id = str(business["id"])
    headers = _headers(business_id)

    invalid_image = await client.put(
        f"/api/v1/local/businesses/{business_id}/branding",
        headers=headers,
        json={"business_logo": {"content_base64": base64.b64encode(b"not an image").decode("ascii")}},
    )
    assert invalid_image.status_code == 400
    assert "valid PNG" in invalid_image.json()["detail"]

    null_name = await client.put(
        f"/api/v1/local/businesses/{business_id}/branding",
        headers=headers,
        json={"display_name": None},
    )
    assert null_name.status_code == 422


def test_local_branding_routes_are_not_mounted_outside_development(settings: Settings) -> None:
    application = create_app(settings)
    route_paths = {getattr(route, "path", None) for route in application.routes}
    assert "/api/v1/local/businesses" not in route_paths
    assert not any(path and path.startswith("/local-assets") for path in route_paths)
