"""M9B Pass 1 protected dashboard APIs and published-image boundaries."""

import base64
from collections.abc import AsyncIterator
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session
from budbot.api.routes.branding import MAX_BRANDING_REQUEST_BYTES
from budbot.core.permissions import permissions_for_role
from budbot.core.security import token_digest
from budbot.core.time import utc_now
from budbot.main import create_app
from budbot.models.assistant import AssistantConfiguration, LocationAssistantOverride
from budbot.models.auth import AdminSession, AuditEvent
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from budbot.services.local_asset_service import LocalAssetStore
from conftest import TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD, seed_owner


@pytest.fixture
async def dashboard_client(settings, db_session, tmp_path) -> AsyncIterator[AsyncClient]:
    app = create_app(settings.model_copy(update={
        "environment": "production", "local_assets_dir": tmp_path / "brand-assets",
        "admin_login_rate_limit_key": SecretStr("synthetic-test-key-for-dashboard-123456"),
    }))

    async def override_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = override_session
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://admin.test") as client:
            await seed_owner(db_session)
            response = await client.post("/api/v1/auth/login", json={
                "email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD,
            })
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            yield client


async def current(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


async def location(client, business_id, name="Main"):
    response = await client.post(f"/api/v1/businesses/{business_id}/locations", json={
        "display_name": name, "address_line_1": "1 Main St", "city": "Portland",
        "region": "Oregon", "region_code": "OR", "postal_code": "97201", "country": "US",
        "timezone": "America/Los_Angeles", "hours": [],
    })
    assert response.status_code == 201, response.text
    return response.json()


def png():
    stream = BytesIO()
    Image.new("RGBA", (16, 12), (10, 100, 80, 128)).save(stream, format="PNG")
    return {"content_base64": base64.b64encode(stream.getvalue()).decode()}


async def foreign_business(session):
    business = Business(display_name="Foreign tenant", industry="general_retail",
        assistant_configuration=AssistantConfiguration(display_name="Private assistant",
            greeting="Welcome", fallback_message="Ask staff", enabled=True))
    session.add(business)
    await session.commit()
    return business


async def test_admin_static_delivery_login_logout_and_production_boundary(dashboard_client):
    client = dashboard_client
    for path, marker in [("/admin/", "BudBot Administration"), ("/admin/src/app.js", "AdminApp"), ("/admin/styles.css", ".masthead")]:
        response = await client.get(path)
        assert response.status_code == 200 and marker in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
    assert (await client.get("/admin/test/app.test.js")).status_code == 404
    assert (await client.get("/api/v1/local/businesses")).status_code == 404
    account = await current(client)
    assert account["businesses"][0]["permissions"] == sorted(permissions_for_role("owner"))
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    # The public sign-in shell is available without an owner cookie.
    assert (await client.get("/admin/")).status_code == 200
    login = await client.post("/api/v1/auth/login", json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD})
    assert login.status_code == 200 and "Secure" in login.headers["set-cookie"]


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "viewer"])
async def test_dashboard_permissions_remain_centralized(dashboard_client, db_session, role):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    loc = await location(client, bid)
    membership = await db_session.scalar(select(BusinessMembership).where(BusinessMembership.business_id == UUID(bid)))
    membership.role = role
    await db_session.commit()
    account = await current(client)
    assert account["businesses"][0]["permissions"] == sorted(permissions_for_role(role))
    for suffix in ["", "/assistant", "/locations", "/compliance-profile", f"/locations/{loc['id']}/assistant-override", f"/compliance-profile/locations/{loc['id']}"]:
        assert (await client.get(f"/api/v1/businesses/{bid}{suffix}")).status_code == 200
    writes = [
        ("PATCH", "", {"products_enabled": False}, "business.write"),
        ("PATCH", "/assistant", {"greeting": "Hello"}, "assistant.write"),
        ("PATCH", f"/locations/{loc['id']}", {"hours": [{"day_of_week": 0, "is_closed": True}]}, "location.write"),
        ("PATCH", f"/locations/{loc['id']}/assistant-override", {"greeting": "Local"}, "assistant.write"),
        ("PUT", "/branding", {"business_logo": png()}, "branding.write"),
    ]
    for method, suffix, payload, permission in writes:
        response = await client.request(method, f"/api/v1/businesses/{bid}{suffix}", json=payload)
        assert response.status_code == (200 if permission in permissions_for_role(role) else 403), response.text


async def test_existing_flags_and_hours_persist_without_new_columns(dashboard_client):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    base = f"/api/v1/businesses/{bid}"
    assert (await client.patch(base, json={"products_enabled": False, "promotions_enabled": False})).status_code == 200
    data = (await client.get(base)).json()
    assert data["products_enabled"] is False and data["promotions_enabled"] is False
    assert (await client.patch(base, json={"products_enabled": None})).status_code == 422
    loc = await location(client, bid)
    endpoint = base + f"/locations/{loc['id']}"
    hours = [{"day_of_week": 0, "open_time": "09:00:00", "close_time": "17:00:00"}, {"day_of_week": 1, "is_closed": True}]
    assert (await client.patch(endpoint, json={"hours": hours})).status_code == 200
    saved = (await client.get(endpoint)).json()["hours"]
    assert {row["day_of_week"] for row in saved} == {0, 1}  # other days remain unconfigured
    assert next(row for row in saved if row["day_of_week"] == 1)["is_closed"] is True
    assert (await client.patch(endpoint, json={"hours": [{"day_of_week": 0, "open_time": "17:00", "close_time": "09:00"}]})).status_code == 422
    assert (await client.post(endpoint + "/deactivate")).json()["active"] is False
    assert (await client.patch(endpoint, json={"active": True})).json()["active"] is True


async def test_override_reads_do_not_materialize_inheritance_and_compliance_is_read_only(dashboard_client, db_session):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    loc = await location(client, bid)
    base = f"/api/v1/businesses/{bid}"
    override_url = base + f"/locations/{loc['id']}/assistant-override"
    effective_url = base + f"/locations/{loc['id']}/effective-assistant"
    assert (await client.get(override_url)).json() is None
    assert list((await db_session.scalars(select(LocationAssistantOverride))).all()) == []
    assert (await client.patch(base + "/assistant", json={"display_name": "Updated assistant", "greeting": "Default greeting"})).status_code == 200
    assert (await client.get(effective_url)).json()["greeting"] == "Default greeting"
    assert (await client.patch(override_url, json={"greeting": "Location greeting", "enabled": False})).status_code == 200
    assert (await client.get(effective_url)).json()["enabled"] is False
    assert (await client.patch(override_url, json={"greeting": None, "enabled": None})).status_code == 200
    assert (await client.get(effective_url)).json()["greeting"] == "Default greeting"
    result = await client.get(base + f"/compliance-profile/locations/{loc['id']}")
    assert result.json()["status"] == "resolved"
    assert result.json()["profile"]["profile_id"] == "general_retail"
    assert (await client.patch(base + f"/compliance-profile/locations/{loc['id']}", json={"requires_age_gate": False})).status_code == 405


async def test_membership_selection_and_cross_tenant_identifiers(dashboard_client, db_session):
    client = dashboard_client
    account = await current(client)
    bid = account["businesses"][0]["business_id"]
    other = await foreign_business(db_session)
    foreign = str(other.id)
    headers = {"X-BudBot-Business-ID": foreign}
    assert (await client.get(f"/api/v1/businesses/{bid}", headers=headers)).status_code == 200
    for method, suffix, payload in [("GET", "", None), ("PATCH", "", {"display_name": "Takeover"}), ("PUT", "/branding", {"business_logo": png()})]:
        response = await client.request(method, f"/api/v1/businesses/{foreign}{suffix}", headers=headers, **({"json": payload} if payload else {}))
        assert response.status_code == 404
    # Same owner legitimately gains a second membership; selection exposes only those two.
    owner = await db_session.scalar(select(UserAccount).where(UserAccount.email == TEST_OWNER_EMAIL))
    membership = BusinessMembership(user_id=owner.id, business_id=UUID(foreign), role="viewer")
    db_session.add(membership)
    await db_session.commit()
    assert {item["business_id"] for item in (await current(client))["businesses"]} == {bid, foreign}
    foreign_loc = await location(client, bid)
    for suffix in [f"/locations/{foreign_loc['id']}/assistant-override", f"/compliance-profile/locations/{foreign_loc['id']}"]:
        assert (await client.get(f"/api/v1/businesses/{foreign}{suffix}")).status_code == 404
    assert (await client.patch(f"/api/v1/businesses/{foreign}/locations/{foreign_loc['id']}", json={"display_name": "Takeover"})).status_code == 403  # viewer
    assert (await client.put(f"/api/v1/businesses/{foreign}/branding", json={"business_logo": png()})).status_code == 403
    await db_session.refresh(membership)
    membership.role = "owner"
    await db_session.commit()
    await current(client)
    assert (await client.patch(f"/api/v1/businesses/{foreign}/locations/{foreign_loc['id']}", json={"display_name": "Takeover"})).status_code == 404
    assert (await client.patch(f"/api/v1/businesses/{foreign}/locations/{foreign_loc['id']}/assistant-override", json={"greeting": "Takeover"})).status_code == 404


async def test_branding_upload_publishes_only_current_assets_and_preserves_public_preview(dashboard_client, db_session, tmp_path):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    base = f"/api/v1/businesses/{bid}"
    saved = await client.put(base + "/branding", json={"business_logo": png(), "assistant_avatar": png()})
    assert saved.status_code == 200, saved.text
    reference = saved.json()["business"]["logo_reference"]
    avatar = saved.json()["assistant"]["avatar_reference"]
    assert reference.startswith(f"/assets/branding/{bid}/")
    assert str(tmp_path) not in saved.text
    # Orphan generated files are not published merely because they exist.
    store = LocalAssetStore(tmp_path / "brand-assets")
    orphan, _ = store.save(UUID(bid), base64.b64decode(png()["content_base64"]))
    async with AsyncClient(transport=client._transport, base_url="https://admin.test") as visitor:
        image = await visitor.get(reference)
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.headers["x-content-type-options"] == "nosniff"
        assert (await visitor.get(orphan.replace("/local-assets/", "/assets/branding/"))).status_code == 404
        assert (await visitor.get(f"/assets/branding/{uuid4()}/{reference.rsplit('/', 1)[-1]}")).status_code == 404
        assert (await visitor.get(base)).status_code == 401
        headers = {"X-BudBot-Business-ID": bid}
        customer = await visitor.post("/api/v1/sessions", headers=headers, json={})
        assert customer.status_code == 201
        widget = await visitor.get(f"/api/v1/sessions/{customer.json()['id']}/widget", headers=headers)
        assert widget.status_code == 200 and widget.json()["business"]["logo_reference"] == reference
        assert set(widget.json()) == {"business", "assistant", "locations", "compliance"}
    assert (await client.put(base + "/branding", json={"remove_business_logo": True})).status_code == 200
    assert (await client.get(reference)).status_code == 404
    assert (await client.get(avatar)).status_code == 200
    audits = list((await db_session.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.branding.saved"))).all())
    assert len(audits) == 2
    assert "content_base64" not in str([event.details for event in audits])


async def test_upload_failures_do_not_publish_partial_images_or_echo_data(dashboard_client, tmp_path):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    base = f"/api/v1/businesses/{bid}"
    bad = {"content_base64": base64.b64encode(b"private-invalid-image").decode()}
    response = await client.put(base + "/branding", json={"business_logo": png(), "assistant_avatar": bad})
    assert response.status_code == 400 and "private-invalid-image" not in response.text
    assert (await client.get(base)).json()["logo_reference"] is None
    assert not list((tmp_path / "brand-assets").rglob("*.png"))
    response = await client.put(base + "/branding", content=b"x" * (MAX_BRANDING_REQUEST_BYTES + 1))
    assert response.status_code == 413
    assert (await client.put(base + "/branding", content=b"not json")).status_code == 422


@pytest.mark.parametrize("invalid", ["missing_csrf", "bad_csrf", "expired", "revoked", "no_cookie"])
async def test_writes_never_bypass_session_or_csrf(dashboard_client, db_session, invalid):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    if invalid == "missing_csrf": client.headers.pop("X-CSRF-Token")
    if invalid == "bad_csrf": client.headers["X-CSRF-Token"] = "invalid"
    if invalid in {"expired", "revoked"}:
        record = await db_session.scalar(select(AdminSession).where(AdminSession.token_digest == token_digest(client.cookies.get("budbot_admin_session"))))
        if invalid == "expired": record.expires_at = utc_now() - timedelta(seconds=1)
        else: record.revoked_at = utc_now()
        await db_session.commit()
    if invalid == "no_cookie": client.cookies.clear()
    expected = 403 if invalid.endswith("csrf") else 401
    for method, suffix, payload in [("PATCH", "", {"products_enabled": False}), ("PUT", "/branding", {"business_logo": png()})]:
        result = await client.request(method, f"/api/v1/businesses/{bid}{suffix}", headers={"X-BudBot-Business-ID": bid}, json=payload)
        assert result.status_code == expected
    if expected == 401:
        assert (await client.get(f"/api/v1/businesses/{bid}")).status_code == 401


async def test_effective_compliance_matches_location_resolution_and_blocks_unknown_jurisdiction(dashboard_client):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    base = f"/api/v1/businesses/{bid}"
    assert (await client.patch(base + "/compliance-profile", json={"profile_id": "oregon_cannabis"})).status_code == 200
    loc = await location(client, bid)
    endpoint = base + f"/compliance-profile/locations/{loc['id']}"
    effective = (await client.get(endpoint)).json()
    assert effective["status"] == "resolved" and effective["jurisdiction_code"] == "US-OR"
    assert effective["profile"]["requires_age_gate"] is True
    assert (await client.patch(base + f"/locations/{loc['id']}", json={"region_code": "ZZ"})).status_code == 200
    effective = (await client.get(endpoint)).json()
    assert effective["status"] == "profile_unavailable" and effective["profile"] is None
    visitor_headers = {"X-BudBot-Business-ID": bid}
    created = await client.post("/api/v1/sessions", headers=visitor_headers, json={"selected_location_id": loc["id"]})
    assert created.status_code == 201 and created.json()["compliance_resolution_status"] == "profile_unavailable"


async def test_legacy_saved_branding_is_published_without_rewriting_business_data(dashboard_client, db_session, tmp_path):
    client = dashboard_client
    bid = (await current(client))["businesses"][0]["business_id"]
    store = LocalAssetStore(tmp_path / "brand-assets")
    reference, _ = store.save(UUID(bid), base64.b64decode(png()["content_base64"]))
    business = await db_session.get(Business, UUID(bid))
    business.logo_reference = reference
    await db_session.commit()
    assert (await client.get(reference.replace("/local-assets/", "/assets/branding/"))).status_code == 200
    assert (await client.get(reference)).status_code == 404  # development alias is absent in production
    assert (await client.get(f"/api/v1/businesses/{bid}")).json()["logo_reference"] == reference
