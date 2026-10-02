"""The customer widget must never depend on an administrative login."""

from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.time import utc_now
from budbot.models.assistant import LocationAssistantOverride
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.session import CustomerSession
from budbot.providers.ai.base import AIFinishReason, AIResponse
from budbot.providers.ai.mock import MockAIProvider
from budbot.providers.ai.registry import AIProviderRegistry


async def _seed(client: AsyncClient, db: AsyncSession, *, cannabis=False):
    me = (await client.get("/api/v1/auth/me")).json()
    business_id = me["businesses"][0]["business_id"]
    business = await db.get(Business, UUID(business_id))
    business.display_name = "Widget Shop"
    business.legal_name = "Private administrative legal name"
    business.logo_reference = (
        f"/local-assets/{business_id}/0123456789abcdef0123456789abcdef.png"
    )
    business.primary_brand_color = "#123456"
    if cannabis:
        business.compliance_domain = "cannabis"
        business.compliance_profile_id = "oregon_cannabis"
    locations = [
        Location(
            business_id=UUID(business_id),
            display_name=name,
            address_line_1="10 Main St",
            city="Portland",
            region="Oregon",
            region_code="OR",
            postal_code="97201",
            country="US",
            timezone="America/Los_Angeles",
            active=active,
        )
        for name, active in [("Main", True), ("Closed", False)]
    ]
    db.add_all(locations)
    await db.flush()
    location_id = str(locations[0].id)
    db.add(LocationAssistantOverride(
        business_id=UUID(business_id), location_id=locations[0].id,
        display_name="Main Helper", greeting="Welcome to Main.",
        fallback_message="Private configuration fallback",
    ))
    await db.commit()
    return business_id, location_id


def _anonymous(client: AsyncClient, business_id: str) -> None:
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    client.headers["X-BudBot-Business-ID"] = business_id


@pytest.mark.asyncio
async def test_original_widget_requests_are_administrative_and_require_login(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    business_id, location_id = await _seed(m2_client, db_session)
    paths = [
        f"/api/v1/businesses/{business_id}{suffix}"
        for suffix in ("", "/assistant", "/locations", "/compliance-profile",
                       f"/locations/{location_id}/effective-assistant")
    ]
    for path in paths:
        assert (await m2_client.get(path)).status_code == 200
    _anonymous(m2_client, business_id)
    for path in paths:
        denied = await m2_client.get(path)
        assert denied.status_code == 401
        assert denied.json() == {"detail": "Authentication is required."}
    denied_write = await m2_client.patch(
        f"/api/v1/businesses/{business_id}", json={"display_name": "Takeover"}
    )
    assert denied_write.status_code == 401


@pytest.mark.asyncio
async def test_public_widget_bootstrap_exposes_only_customer_identity_and_branding(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    business_id, location_id = await _seed(m2_client, db_session)
    _anonymous(m2_client, business_id)
    created = await m2_client.post("/api/v1/sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["id"]
    path = f"/api/v1/sessions/{session_id}/widget"
    initial = await m2_client.get(path)
    assert initial.status_code == 200, initial.text
    assert initial.headers["cache-control"] == "no-store"
    data = initial.json()
    assert set(data) == {"business", "assistant", "locations", "compliance"}
    assert data["business"] == {
        "display_name": "Widget Shop",
        "logo_reference": f"/local-assets/{business_id}/0123456789abcdef0123456789abcdef.png",
        "primary_brand_color": "#123456",
    }
    assert data["assistant"] == {
        "display_name": "Test Assistant", "greeting": "Welcome.",
        "avatar_reference": None, "primary_color": "#123456",
    }
    assert data["locations"] == [{"id": location_id, "display_name": "Main"}]
    assert set(data["compliance"]) == {"requires_age_gate", "website_attestation_notice"}
    assert data["compliance"]["requires_age_gate"] is False
    selected = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        json={"selected_location_id": location_id},
    )
    assert selected.status_code == 200
    effective = await m2_client.get(path)
    assert effective.status_code == 200
    assert effective.json()["assistant"] == {
        **data["assistant"], "display_name": "Main Helper", "greeting": "Welcome to Main.",
    }
    assert "Private" not in effective.text
    assert (await m2_client.get(f"/api/v1/commands?session_id={session_id}")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "cross_tenant", "expired", "inactive"])
async def test_widget_bootstrap_requires_live_same_tenant_customer_session(
    m2_client: AsyncClient, db_session: AsyncSession, failure: str
) -> None:
    business_id, _ = await _seed(m2_client, db_session)
    _anonymous(m2_client, business_id)
    created = await m2_client.post("/api/v1/sessions", json={})
    session_id = created.json()["id"]
    expected = 404
    if failure == "missing":
        session_id = str(uuid4())
    elif failure == "cross_tenant":
        m2_client.headers["X-BudBot-Business-ID"] = str(uuid4())
    elif failure == "expired":
        customer = await db_session.get(CustomerSession, UUID(session_id))
        customer.expires_at = utc_now() - timedelta(seconds=1)
        expected = 410
    else:
        business = await db_session.get(Business, UUID(business_id))
        business.active = False
    await db_session.commit()
    response = await m2_client.get(f"/api/v1/sessions/{session_id}/widget")
    assert response.status_code == expected
    if failure == "expired":
        assert response.json()["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_public_widget_compliance_follows_customer_location_and_attestation(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    business_id, location_id = await _seed(m2_client, db_session, cannabis=True)
    _anonymous(m2_client, business_id)
    created = await m2_client.post("/api/v1/sessions", json={})
    session_id = created.json()["id"]
    initial = await m2_client.get(f"/api/v1/sessions/{session_id}/widget")
    assert initial.status_code == 200
    assert initial.json()["compliance"]["requires_age_gate"] is True
    selected = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        json={"selected_location_id": location_id},
    )
    assert selected.json()["age_gate_status"] == "REQUIRED_UNVERIFIED"
    bootstrap = await m2_client.get(f"/api/v1/sessions/{session_id}/widget")
    assert bootstrap.status_code == 200
    assert "government-ID verification" in bootstrap.json()["compliance"]["website_attestation_notice"]
    blocked = await m2_client.post(
        "/api/v1/commands/execute", json={"session_id": session_id, "input": "/products"}
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "AGE_VERIFICATION_REQUIRED"
    attested = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        json={"confirmed_21_or_older": True},
    )
    assert attested.status_code == 200
    assert attested.json()["age_gate_status"] == "VERIFIED"
    allowed = await m2_client.post(
        "/api/v1/commands/execute", json={"session_id": session_id, "input": "/products"}
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_widget_chat_uses_customer_session_without_admin_cookie(
    m2_client: AsyncClient, db_session: AsyncSession, application: FastAPI
) -> None:
    business_id, location_id = await _seed(m2_client, db_session)
    _anonymous(m2_client, business_id)
    created = await m2_client.post(
        "/api/v1/sessions", json={"selected_location_id": location_id}
    )
    session_id = created.json()["id"]
    application.state.settings = application.state.settings.model_copy(update={
        "ai_enabled": True, "ai_provider": "mock", "ai_model": "widget-test-model",
        "ai_harness": "generic_openai", "ai_capability_tool_calling": True,
    })
    provider = MockAIProvider([AIResponse(
        content="Unverified provider prose", finish_reason=AIFinishReason.STOP,
        tool_calls=(), provider="mock", model="widget-test-model", harness="generic_openai",
    )])
    registry = AIProviderRegistry()
    registry.register("mock", provider)
    application.state.ai_provider_registry = registry
    missing = await m2_client.post("/api/v1/chat", json={"message": "Hello"})
    assert missing.status_code == 422
    unknown = await m2_client.post(
        "/api/v1/chat", json={"session_id": str(uuid4()), "message": "Hello"}
    )
    assert unknown.status_code == 404
    assert not provider.requests
    response = await m2_client.post(
        "/api/v1/chat", json={"session_id": session_id, "message": "Hello"}
    )
    assert response.status_code == 200, response.text
    assert len(provider.requests) == 1
    assert "Unverified provider prose" not in response.text
    assert not m2_client.cookies


@pytest.mark.asyncio
async def test_widget_projection_cannot_bypass_stale_compliance_binding(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    business_id, location_id = await _seed(m2_client, db_session, cannabis=True)
    _anonymous(m2_client, business_id)
    created = await m2_client.post(
        "/api/v1/sessions", json={"selected_location_id": location_id}
    )
    session_id = created.json()["id"]
    business = await db_session.get(Business, UUID(business_id))
    business.compliance_domain = "general_retail"
    await db_session.commit()
    stale = await m2_client.get(f"/api/v1/sessions/{session_id}/widget")
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMPLIANCE_PROFILE_MISMATCH"
