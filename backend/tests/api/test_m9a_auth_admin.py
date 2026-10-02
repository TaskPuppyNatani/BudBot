"""M9A authentication, session lifecycle, roles, and tenant boundaries."""

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.security import hash_password, token_digest
from budbot.core.time import ensure_utc, utc_now
from budbot.models.assistant import AssistantConfiguration
from budbot.models.auth import AdminSession, AuditEvent, AuthSetupState, LoginRateLimit
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from conftest import TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD


async def _owner_business_id(client: AsyncClient) -> str:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["businesses"][0]["business_id"]


def _business(name: str) -> Business:
    return Business(
        display_name=name,
        industry="general_retail",
        default_timezone="UTC",
        assistant_configuration=AssistantConfiguration(
            display_name=f"{name} Assistant",
            greeting="Welcome.",
            fallback_message="Please ask a team member.",
            enabled=True,
        ),
    )


@pytest.mark.asyncio
async def test_login_is_generic_and_persists_only_opaque_session_digest(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = m2_client
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)

    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.test", "password": TEST_OWNER_PASSWORD},
    )
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": "incorrect password"},
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json() == {
        "detail": "Invalid email or password."
    }
    assert not unknown.headers.get("set-cookie")
    oversized_password = "s" * 1025
    malformed = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": oversized_password},
    )
    assert malformed.status_code == 422
    assert oversized_password not in malformed.text

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL.upper(), "password": TEST_OWNER_PASSWORD},
    )
    assert login.status_code == 200
    assert login.headers["cache-control"] == "no-store"
    cookie_header = login.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Secure" not in cookie_header
    token = client.cookies.get("budbot_admin_session")
    assert token and token in cookie_header

    records = list((await db_session.scalars(select(AdminSession))).all())
    assert len(records) == 2  # one fixture login and this fresh login
    assert all(record.token_digest != token for record in records)
    assert any(record.token_digest == token_digest(token) for record in records)
    assert login.json()["businesses"]
    current = await client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.headers["cache-control"] == "no-store"

    audit = list((await db_session.scalars(select(AuditEvent))).all())
    assert any(event.event_type == "auth.login.succeeded" for event in audit)
    assert "password" not in str([event.details for event in audit]).casefold()


@pytest.mark.asyncio
async def test_login_throttle_uses_independent_keyed_email_and_peer_buckets(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = m2_client
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": TEST_OWNER_EMAIL, "password": "incorrect password"},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password."}

    buckets = list((await db_session.scalars(select(LoginRateLimit))).all())
    assert len(buckets) == 2
    assert len({bucket.key_digest for bucket in buckets}) == 2
    assert all(bucket.failed_attempts == 5 for bucket in buckets)
    assert all(bucket.blocked_until is not None for bucket in buckets)


@pytest.mark.asyncio
async def test_active_login_lockout_survives_shorter_failure_window_without_audit_flood(
    application: FastAPI,
    m2_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    application.state.settings = application.state.settings.model_copy(
        update={
            "admin_login_failure_limit": 3,
            "admin_login_window_seconds": 60,
            "admin_login_lockout_seconds": 600,
        }
    )
    client = m2_client
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)

    for _ in range(3):
        failed = await client.post(
            "/api/v1/auth/login",
            json={"email": TEST_OWNER_EMAIL, "password": "incorrect password"},
        )
        assert failed.status_code == 401

    buckets = list((await db_session.scalars(select(LoginRateLimit))).all())
    assert len(buckets) == 2
    assert all(bucket.blocked_until is not None for bucket in buckets)
    assert all(bucket.failed_attempts == 3 for bucket in buckets)
    for bucket in buckets:
        bucket.window_started_at = utc_now() - timedelta(seconds=61)
    await db_session.commit()

    rejected_retry = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert rejected_retry.status_code == 401
    assert not rejected_retry.headers.get("set-cookie")
    buckets = list((await db_session.scalars(select(LoginRateLimit))).all())
    assert all(bucket.blocked_until is not None for bucket in buckets)
    assert all(
        bucket.blocked_until is not None
        and ensure_utc(bucket.blocked_until) > utc_now()
        for bucket in buckets
    )
    assert all(bucket.failed_attempts == 3 for bucket in buckets)
    failure_events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "auth.login.failed")
            )
        ).all()
    )
    assert len(failure_events) == 3
    assert any(event.details["outcome"] == "locked" for event in failure_events)


@pytest.mark.asyncio
async def test_login_rotation_csrf_logout_expiry_and_logout_all(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = m2_client
    original_token = client.cookies.get("budbot_admin_session")
    assert original_token
    original_csrf = client.headers["X-CSRF-Token"]

    denied = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": ""}
    )
    assert denied.status_code == 403
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    client.headers["X-CSRF-Token"] = (await client.get("/api/v1/auth/me")).json()[
        "csrf_token"
    ]
    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    # Logging in while a cookie is present replaces it with a newly issued
    # opaque server-side session instead of adopting caller-controlled state.
    client.cookies.clear()
    client.cookies.set(
        "budbot_admin_session", "chosen-by-caller", domain="testserver.local", path="/"
    )
    rotated = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert rotated.status_code == 200
    second_token = client.cookies.get("budbot_admin_session")
    assert second_token and second_token not in {original_token, "chosen-by-caller"}
    assert rotated.json()["csrf_token"] != original_csrf
    client.headers["X-CSRF-Token"] = rotated.json()["csrf_token"]

    old_session = await db_session.scalar(
        select(AdminSession).where(
            AdminSession.token_digest == token_digest(second_token)
        )
    )
    assert old_session is not None
    old_session.expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    # Login again to exercise explicit revocation and logout-all.
    third = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert third.status_code == 200
    third_token = client.cookies.get("budbot_admin_session")
    third_csrf = third.json()["csrf_token"]
    assert third_token
    client.headers["X-CSRF-Token"] = third_csrf
    fourth = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
    )
    assert fourth.status_code == 200
    fourth_token = client.cookies.get("budbot_admin_session")
    assert fourth_token and fourth_token != third_token

    client.cookies.set(
        "budbot_admin_session", third_token, domain="testserver.local", path="/"
    )
    client.headers["X-CSRF-Token"] = third_csrf
    logout_all = await client.post("/api/v1/auth/logout-all")
    assert logout_all.status_code == 204
    assert "budbot_admin_session" not in client.cookies

    client.cookies.set("budbot_admin_session", fourth_token)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_all_admin_reads_and_writes_require_auth_even_with_tenant_header(
    m2_client: AsyncClient,
) -> None:
    client = m2_client
    business_id = await _owner_business_id(client)
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    headers = {"X-BudBot-Business-ID": business_id}

    reads = [
        ("GET", f"/api/v1/businesses/{business_id}"),
        ("GET", f"/api/v1/businesses/{business_id}/locations"),
        ("GET", f"/api/v1/businesses/{business_id}/assistant"),
        ("GET", f"/api/v1/businesses/{business_id}/compliance-profile"),
    ]
    for method, path in reads:
        response = await client.request(method, path, headers=headers)
        assert response.status_code == 401, (path, response.text)


@pytest.mark.asyncio
async def test_cookie_authenticated_configuration_write_requires_csrf(
    m2_client: AsyncClient,
) -> None:
    client = m2_client
    business_id = await _owner_business_id(client)
    denied = await client.patch(
        f"/api/v1/businesses/{business_id}",
        headers={"X-CSRF-Token": ""},
        json={"display_name": "No CSRF"},
    )
    assert denied.status_code == 403

    writes = [
        ("PATCH", f"/api/v1/businesses/{business_id}", {"display_name": "No"}),
        (
            "PATCH",
            f"/api/v1/businesses/{business_id}/assistant",
            {"display_name": "No"},
        ),
        (
            "PATCH",
            f"/api/v1/businesses/{business_id}/compliance-profile",
            {"profile_id": "general_retail"},
        ),
    ]
    for method, path, payload in writes:
        response = await client.request(
            method,
            path,
            headers={"X-CSRF-Token": ""},
            json=payload,
        )
        assert response.status_code == 403, (path, response.text)


@pytest.mark.asyncio
async def test_membership_roles_multi_business_and_old_header_do_not_grant_access(
    m2_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = m2_client
    first_id = await _owner_business_id(client)
    created = await client.post(
        "/api/v1/businesses",
        json={
            "display_name": "Owner Second Business",
            "industry": "general_retail",
            "default_timezone": "UTC",
            "assistant": {
                "display_name": "Second Assistant",
                "greeting": "Welcome.",
                "fallback_message": "Ask a team member.",
            },
        },
    )
    assert created.status_code == 201, created.text
    owner_memberships = (await client.get("/api/v1/auth/me")).json()["businesses"]
    assert {item["business_id"] for item in owner_memberships} == {
        first_id,
        created.json()["id"],
    }

    unowned = _business("Unowned Business")
    viewer = UserAccount(
        email="m9a-viewer@example.test",
        display_name="Viewer",
        password_hash=hash_password("m9a-viewer-test-passphrase"),
        active=True,
    )
    db_session.add_all([unowned, viewer])
    await db_session.flush()
    viewer_email = viewer.email
    db_session.add(
        BusinessMembership(user_id=viewer.id, business_id=unowned.id, role="viewer")
    )
    await db_session.commit()

    unowned_id = str(unowned.id)
    unauthorized = await client.get(
        f"/api/v1/businesses/{unowned_id}",
        headers={"X-BudBot-Business-ID": unowned_id},
    )
    assert unauthorized.status_code == 404

    client.cookies.clear()
    viewer_login = await client.post(
        "/api/v1/auth/login",
        json={"email": viewer_email, "password": "m9a-viewer-test-passphrase"},
    )
    assert viewer_login.status_code == 200
    client.headers["X-CSRF-Token"] = viewer_login.json()["csrf_token"]
    viewer_businesses = viewer_login.json()["businesses"]
    assert [item["business_id"] for item in viewer_businesses] == [unowned_id]

    no_create = await client.post(
        "/api/v1/businesses",
        json={
            "display_name": "Viewer Cannot Create",
            "industry": "general_retail",
            "default_timezone": "UTC",
            "assistant": {
                "display_name": "Assistant",
                "greeting": "Welcome.",
                "fallback_message": "Ask a team member.",
            },
        },
    )
    assert no_create.status_code == 403

    # An unrelated header cannot select another tenant, while the same viewer
    # retains read-only access to the one verified membership.
    read = await client.get(
        f"/api/v1/businesses/{unowned_id}",
        headers={"X-BudBot-Business-ID": first_id},
    )
    assert read.status_code == 200
    write = await client.patch(
        f"/api/v1/businesses/{unowned_id}",
        headers={"X-BudBot-Business-ID": unowned_id},
        json={"display_name": "Viewer Cannot Rename"},
    )
    assert write.status_code == 403
    crossed = await client.get(
        f"/api/v1/businesses/{first_id}",
        headers={"X-BudBot-Business-ID": unowned_id},
    )
    assert crossed.status_code == 404


@pytest.mark.asyncio
async def test_public_customer_session_and_compliance_projection_remain_available(
    m2_client: AsyncClient,
) -> None:
    client = m2_client
    business_id = await _owner_business_id(client)
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    headers = {"X-BudBot-Business-ID": business_id}

    created = await client.post("/api/v1/sessions", headers=headers, json={})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    age_gate = await client.get(
        f"/api/v1/sessions/{session_id}/age-gate", headers=headers
    )
    assert age_gate.status_code == 200
    assert age_gate.json()["age_gate_status"] == "NOT_REQUIRED"
    assert (
        await client.get(f"/api/v1/businesses/{business_id}/compliance-profile")
    ).status_code == 401


@pytest.mark.asyncio
async def test_owner_setup_selects_one_tenant_once_and_supports_empty_installation(
    db_session: AsyncSession,
) -> None:
    from budbot.services.owner_setup_service import OwnerSetupError, OwnerSetupService

    first, second = _business("Selected Owner Business"), _business("Other Tenant")
    db_session.add_all([first, second])
    await db_session.flush()
    first_id, second_id = first.id, second.id
    await db_session.commit()

    async with db_session.begin():
        result = await OwnerSetupService(db_session).initialize_first_owner(
            email="first-owner@example.test",
            display_name="First Owner",
            password_hash=hash_password("first-owner-test-passphrase"),
            business_id=first_id,
        )
    assert result.business_id == first_id
    memberships = list((await db_session.scalars(select(BusinessMembership))).all())
    assert [(item.user_id, item.business_id, item.role) for item in memberships] == [
        (result.user_id, first_id, "owner")
    ]
    state = await db_session.get(AuthSetupState, 1)
    assert state is not None and state.owner_user_id == result.user_id
    await db_session.commit()

    with pytest.raises(OwnerSetupError, match="already been initialized"):
        async with db_session.begin():
            await OwnerSetupService(db_session).initialize_first_owner(
                email="attacker@example.test",
                display_name="Attacker",
                password_hash=hash_password("attacker-test-passphrase"),
                business_id=second_id,
            )
    assert await db_session.scalar(
        select(UserAccount.id).where(UserAccount.email == "attacker@example.test")
    ) is None


@pytest.mark.asyncio
async def test_owner_setup_creates_first_business_when_database_is_empty(
    db_session: AsyncSession,
) -> None:
    from budbot.services.owner_setup_service import OwnerSetupService

    async with db_session.begin():
        result = await OwnerSetupService(db_session).initialize_first_owner(
            email="fresh-owner@example.test",
            display_name="Fresh Owner",
            password_hash=hash_password("fresh-owner-test-passphrase"),
            business_id=None,
            new_business_name="Fresh Self Hosted Business",
        )
    assert result.business_name == "Fresh Self Hosted Business"
    membership = await db_session.scalar(
        select(BusinessMembership).where(
            BusinessMembership.user_id == result.user_id,
            BusinessMembership.business_id == result.business_id,
        )
    )
    assert membership is not None and membership.role == "owner"
