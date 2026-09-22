"""M3 customer-session, profile, age-gate, and HTTP-enforcement tests."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.engine import AuthorizationDecision, requires_capability
from budbot.compliance.registry import Capability
from budbot.models.business import Business
from budbot.models.session import CustomerSession


def business_payload(name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "industry": "general_retail",
        "default_timezone": "America/Los_Angeles",
        "assistant": {
            "display_name": f"{name} Helper",
            "greeting": f"Welcome to {name}",
            "fallback_message": "Please ask a team member.",
            "enabled": True,
        },
    }


def location_payload(name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "address_line_1": f"1 {name} Street",
        "city": "Portland",
        "region": "OR",
        "postal_code": "97201",
        "country": "us",
        "timezone": "America/Los_Angeles",
    }


def tenant_header(business_id: str) -> dict[str, str]:
    return {"X-BudBot-Business-ID": business_id}


async def create_business(client: AsyncClient, name: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/businesses", json=business_payload(name)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_location(
    client: AsyncClient, business_id: str, name: str
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=tenant_header(business_id),
        json=location_payload(name),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def configure_profile(
    client: AsyncClient, business_id: str, profile_id: str
) -> dict[str, object]:
    response = await client.patch(
        f"/api/v1/businesses/{business_id}/compliance-profile",
        headers=tenant_header(business_id),
        json={"profile_id": profile_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def install_test_capability_routes(application: FastAPI) -> None:
    """Install only in-test routes to prove dependency enforcement."""

    router = APIRouter(prefix="/_m3_test")

    @router.get("/products/{session_id}")
    async def protected_products(
        decision: Annotated[
            AuthorizationDecision,
            Depends(requires_capability(Capability.CANNABIS_PRODUCTS)),
        ],
    ) -> dict[str, bool]:
        return {"allowed": decision.allowed}

    @router.get("/hours/{session_id}")
    async def public_hours(
        decision: Annotated[
            AuthorizationDecision,
            Depends(requires_capability(Capability.BUSINESS_HOURS)),
        ],
    ) -> dict[str, bool]:
        return {"allowed": decision.allowed}

    @router.get("/medical/{session_id}")
    async def prohibited_medical_advice(
        decision: Annotated[
            AuthorizationDecision,
            Depends(requires_capability(Capability.MEDICAL_ADVICE)),
        ],
    ) -> dict[str, bool]:
        return {"allowed": decision.allowed}

    application.include_router(router)


async def test_profiles_default_selection_and_tenant_scoped_configuration(
    m2_client: AsyncClient,
) -> None:
    first = await create_business(m2_client, "General")
    second = await create_business(m2_client, "Cannabis")
    first_id, second_id = str(first["id"]), str(second["id"])

    assert first["compliance_profile_id"] == "general_retail"
    assert first["compliance_profile_version"] == "1.0"
    default_profile = await m2_client.get(
        f"/api/v1/businesses/{first_id}/compliance-profile",
        headers=tenant_header(first_id),
    )
    assert default_profile.status_code == 200
    assert default_profile.json()["requires_age_gate"] is False

    configured = await configure_profile(m2_client, second_id, "oregon_cannabis")
    assert configured["profile_id"] == "oregon_cannabis"
    assert configured["version"] == "1.0"
    assert configured["minimum_age"] == 21
    assert "government-ID verification" in configured["website_attestation_notice"]

    cross_tenant = await m2_client.patch(
        f"/api/v1/businesses/{second_id}/compliance-profile",
        headers=tenant_header(first_id),
        json={"profile_id": "general_retail"},
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["code"] == "BUSINESS_NOT_FOUND"

    unknown = await m2_client.patch(
        f"/api/v1/businesses/{first_id}/compliance-profile",
        headers=tenant_header(first_id),
        json={"profile_id": "unknown_profile"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "UNKNOWN_COMPLIANCE_PROFILE"


async def test_session_creation_is_opaque_tenant_scoped_and_snapshots_profile(
    m2_client: AsyncClient,
) -> None:
    general = await create_business(m2_client, "General")
    cannabis = await create_business(m2_client, "Cannabis")
    general_id, cannabis_id = str(general["id"]), str(cannabis["id"])
    location = await create_location(m2_client, general_id, "Main")
    await configure_profile(m2_client, cannabis_id, "oregon_cannabis")

    general_session_response = await m2_client.post(
        "/api/v1/sessions",
        headers=tenant_header(general_id),
        json={"selected_location_id": location["id"]},
    )
    assert general_session_response.status_code == 201
    general_session = general_session_response.json()
    UUID(general_session["id"])
    assert general_session["id"] != general_id
    assert general_session["business_id"] == general_id
    assert general_session["selected_location_id"] == location["id"]
    assert general_session["age_gate_status"] == AgeGateStatus.NOT_REQUIRED
    assert "date_of_birth" not in general_session
    assert "government_id" not in general_session

    cannabis_session_response = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(cannabis_id), json={}
    )
    assert cannabis_session_response.status_code == 201
    cannabis_session = cannabis_session_response.json()
    assert cannabis_session["compliance_profile_id"] == "oregon_cannabis"
    assert cannabis_session["compliance_profile_version"] == "1.0"
    assert cannabis_session["age_gate_status"] == AgeGateStatus.REQUIRED_UNVERIFIED

    cross_read = await m2_client.get(
        f"/api/v1/sessions/{cannabis_session['id']}",
        headers=tenant_header(general_id),
    )
    assert cross_read.status_code == 404
    assert cross_read.json()["code"] == "SESSION_NOT_FOUND"


async def test_location_selection_requires_active_same_tenant_location(
    m2_client: AsyncClient,
) -> None:
    first = await create_business(m2_client, "First")
    second = await create_business(m2_client, "Second")
    first_id, second_id = str(first["id"]), str(second["id"])
    active = await create_location(m2_client, first_id, "Active")
    active_second = await create_location(m2_client, first_id, "Active Second")
    inactive = await create_location(m2_client, first_id, "Inactive")
    other = await create_location(m2_client, second_id, "Other")
    deactivated = await m2_client.post(
        f"/api/v1/businesses/{first_id}/locations/{inactive['id']}/deactivate",
        headers=tenant_header(first_id),
    )
    assert deactivated.status_code == 200

    session_response = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(first_id), json={}
    )
    session_id = session_response.json()["id"]

    selected = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(first_id),
        json={"selected_location_id": active["id"]},
    )
    assert selected.status_code == 200
    assert selected.json()["selected_location_id"] == active["id"]

    switched = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(first_id),
        json={"selected_location_id": active_second["id"]},
    )
    assert switched.status_code == 200
    assert switched.json()["selected_location_id"] == active_second["id"]

    cleared = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(first_id),
        json={"selected_location_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["selected_location_id"] is None

    cross_tenant = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(first_id),
        json={"selected_location_id": other["id"]},
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["code"] == "LOCATION_NOT_FOUND"

    inactive_response = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(first_id),
        json={"selected_location_id": inactive["id"]},
    )
    assert inactive_response.status_code == 409
    assert inactive_response.json()["code"] == "LOCATION_INACTIVE"

    cross_mutation = await m2_client.patch(
        f"/api/v1/sessions/{session_id}/location",
        headers=tenant_header(second_id),
        json={"selected_location_id": other["id"]},
    )
    assert cross_mutation.status_code == 404
    assert cross_mutation.json()["code"] == "SESSION_NOT_FOUND"


async def test_profile_version_only_change_invalidates_session(
    m2_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from budbot.compliance.profiles.general_retail import GENERAL_RETAIL_PROFILE
    from budbot.compliance.registry import COMPLIANCE_PROFILES

    monkeypatch.setitem(
        COMPLIANCE_PROFILES,
        ("general_retail", "2.0"),
        replace(GENERAL_RETAIL_PROFILE, version="2.0"),
    )

    business = await create_business(m2_client, "Versioned")
    business_id = str(business["id"])
    created = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(business_id), json={}
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    stored_business = await db_session.scalar(
        select(Business).where(Business.id == UUID(business_id))
    )
    assert stored_business is not None
    stored_business.compliance_profile_version = "2.0"
    await db_session.flush()

    stale = await m2_client.get(
        f"/api/v1/sessions/{session_id}",
        headers=tenant_header(business_id),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMPLIANCE_PROFILE_MISMATCH"


async def test_age_gate_and_direct_http_enforcement(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session: AsyncSession,
) -> None:
    install_test_capability_routes(application)
    business = await create_business(m2_client, "Oregon")
    business_id = str(business["id"])
    await configure_profile(m2_client, business_id, "oregon_cannabis")
    created = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(business_id), json={}
    )
    session_id = created.json()["id"]
    headers = tenant_header(business_id)

    before = await m2_client.get(f"/_m3_test/products/{session_id}", headers=headers)
    assert before.status_code == 403
    assert before.json()["code"] == "AGE_VERIFICATION_REQUIRED"
    state = await m2_client.get(
        f"/api/v1/sessions/{session_id}/age-gate", headers=headers
    )
    assert state.status_code == 200
    assert state.json()["age_gate_status"] == AgeGateStatus.REQUIRED_UNVERIFIED
    public = await m2_client.get(f"/_m3_test/hours/{session_id}", headers=headers)
    assert public.status_code == 200
    assert public.json() == {"allowed": True}

    attested = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": True},
    )
    assert attested.status_code == 200
    assert attested.json()["age_gate_status"] == AgeGateStatus.VERIFIED
    assert attested.json()["age_attested_at"] is not None
    after = await m2_client.get(f"/_m3_test/products/{session_id}", headers=headers)
    assert after.status_code == 200
    assert after.json() == {"allowed": True}

    repeat = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": True},
    )
    assert repeat.status_code == 200
    assert repeat.json()["age_gate_status"] == AgeGateStatus.VERIFIED

    medical = await m2_client.get(f"/_m3_test/medical/{session_id}", headers=headers)
    assert medical.status_code == 403
    assert medical.json()["code"] == "CAPABILITY_PROHIBITED"

    stored = await db_session.scalar(
        select(CustomerSession).where(CustomerSession.id == UUID(session_id))
    )
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()
    expired = await m2_client.get(
        f"/_m3_test/products/{session_id}", headers=headers
    )
    assert expired.status_code == 410
    assert expired.json()["code"] == "SESSION_EXPIRED"

    accidental_reverify = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": True},
    )
    assert accidental_reverify.status_code == 410
    assert accidental_reverify.json()["code"] == "SESSION_EXPIRED"


async def test_denial_is_persisted_and_cannot_be_upgraded(
    m2_client: AsyncClient,
    application: FastAPI,
) -> None:
    install_test_capability_routes(application)
    business = await create_business(m2_client, "Denied")
    business_id = str(business["id"])
    await configure_profile(m2_client, business_id, "oregon_cannabis")
    created = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(business_id), json={}
    )
    session_id = created.json()["id"]
    headers = tenant_header(business_id)
    denied = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": False},
    )
    assert denied.status_code == 200
    assert denied.json()["age_gate_status"] == AgeGateStatus.DENIED

    blocked = await m2_client.get(f"/_m3_test/products/{session_id}", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "AGE_VERIFICATION_DENIED"
    reattempt = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": True},
    )
    assert reattempt.status_code == 403
    assert reattempt.json()["code"] == "AGE_VERIFICATION_DENIED"


async def test_general_retail_is_not_oregon_gated_and_profile_changes_stale_sessions(
    m2_client: AsyncClient,
    application: FastAPI,
) -> None:
    install_test_capability_routes(application)
    business = await create_business(m2_client, "General")
    business_id = str(business["id"])
    headers = tenant_header(business_id)
    created = await m2_client.post("/api/v1/sessions", headers=headers, json={})
    general_session_id = created.json()["id"]
    public = await m2_client.get(
        f"/_m3_test/hours/{general_session_id}", headers=headers
    )
    assert public.status_code == 200
    not_oregon_gated = await m2_client.get(
        f"/_m3_test/products/{general_session_id}", headers=headers
    )
    assert not_oregon_gated.status_code == 403
    assert not_oregon_gated.json()["code"] == "CAPABILITY_PROHIBITED"
    no_fake_gate = await m2_client.post(
        f"/api/v1/sessions/{general_session_id}/age-attestation",
        headers=headers,
        json={"confirmed_21_or_older": False},
    )
    assert no_fake_gate.status_code == 200
    assert no_fake_gate.json()["age_gate_status"] == AgeGateStatus.NOT_REQUIRED
    assert no_fake_gate.json()["age_attested_at"] is None

    await configure_profile(m2_client, business_id, "oregon_cannabis")
    stale_read = await m2_client.get(
        f"/api/v1/sessions/{general_session_id}", headers=headers
    )
    assert stale_read.status_code == 409
    assert stale_read.json()["code"] == "COMPLIANCE_PROFILE_MISMATCH"
    stale = await m2_client.get(
        f"/_m3_test/products/{general_session_id}", headers=headers
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "COMPLIANCE_PROFILE_MISMATCH"

    new_session = await m2_client.post("/api/v1/sessions", headers=headers, json={})
    assert new_session.json()["age_gate_status"] == AgeGateStatus.REQUIRED_UNVERIFIED


async def test_tenant_a_cannot_attest_or_use_tenant_b_session(
    m2_client: AsyncClient,
    application: FastAPI,
) -> None:
    install_test_capability_routes(application)
    first = await create_business(m2_client, "A")
    second = await create_business(m2_client, "B")
    first_id, second_id = str(first["id"]), str(second["id"])
    await configure_profile(m2_client, second_id, "oregon_cannabis")
    created = await m2_client.post(
        "/api/v1/sessions", headers=tenant_header(second_id), json={}
    )
    session_id = created.json()["id"]

    attest = await m2_client.post(
        f"/api/v1/sessions/{session_id}/age-attestation",
        headers=tenant_header(first_id),
        json={"confirmed_21_or_older": True},
    )
    assert attest.status_code == 404
    assert attest.json()["code"] == "SESSION_NOT_FOUND"
    use = await m2_client.get(
        f"/_m3_test/products/{session_id}", headers=tenant_header(first_id)
    )
    assert use.status_code == 404
    assert use.json()["code"] == "SESSION_NOT_FOUND"
