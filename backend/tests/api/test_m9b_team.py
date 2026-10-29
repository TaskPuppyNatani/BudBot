"""M9B Team and invitation API authorization, tenant, and lifecycle coverage."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session
from budbot.core.security import hash_password, token_digest
from budbot.core.time import utc_now
from budbot.main import create_app
from budbot.models.auth import AuditEvent
from budbot.models.business import Business
from budbot.models.invitation import BusinessInvitation
from budbot.models.user import BusinessMembership, UserAccount
from conftest import TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD, seed_owner

ORIGIN = "https://team.test"


@pytest.fixture
async def team_client(settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    settings = settings.model_copy(update={
        "environment": "production",
        "admin_login_rate_limit_key": SecretStr("synthetic-team-rate-key-for-tests-123456789"),
        "admin_invitation_ttl_seconds": 3600,
    })
    app = create_app(settings)

    async def override_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = override_session
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
            await seed_owner(db_session)
            response = await client.post("/api/v1/auth/login", json={
                "email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD,
            })
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            yield client
    app.dependency_overrides.clear()


async def current(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


async def create_invite(client, business_id, email="new-person@example.test", role="manager"):
    return await client.post(
        f"/api/v1/businesses/{business_id}/invitations",
        headers={"Origin": ORIGIN}, json={"email": email, "role": role},
    )


async def test_invite_new_account_is_single_use_and_secret_is_write_only(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    created = await create_invite(client, business_id, " New.Person@Example.test ", "manager")
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["token"]
    invitation = await db_session.get(BusinessInvitation, UUID(body["invitation_id"]))
    assert invitation is not None and invitation.recipient_email == "new.person@example.test"
    assert invitation.token_digest == token_digest(token) and token not in invitation.token_digest

    listed = await client.get(f"/api/v1/businesses/{business_id}/members")
    assert listed.status_code == 200
    assert "token" not in listed.text and token not in listed.text
    assert listed.json()["invitations"][0]["email"] == "new.person@example.test"

    client.cookies.clear()
    assert (await client.get(f"/api/v1/businesses/{business_id}/members")).status_code == 401
    preview = await client.post(
        "/api/v1/invitations/inspect", headers={"Origin": ORIGIN}, json={"token": token}
    )
    assert preview.status_code == 200 and preview.json()["business_name"] == "M9A Test Business"
    assert (await client.post(
        "/api/v1/invitations/inspect", headers={"Origin": "https://evil.test"}, json={"token": token}
    )).status_code == 403

    accepted = await client.post(
        "/api/v1/invitations/accept/new", headers={"Origin": ORIGIN},
        json={"token": token, "display_name": "New Teammate", "password": "a-very-good-passphrase"},
    )
    assert accepted.status_code == 200, accepted.text
    assert "token" not in accepted.text and "password" not in accepted.text
    replay = await client.post(
        "/api/v1/invitations/accept/new", headers={"Origin": ORIGIN},
        json={"token": token, "display_name": "New Teammate", "password": "a-very-good-passphrase"},
    )
    assert replay.status_code == 404
    account = await db_session.scalar(select(UserAccount).where(UserAccount.email == "new.person@example.test"))
    assert account is not None and account.password_hash != "a-very-good-passphrase"
    membership = await db_session.scalar(select(BusinessMembership).where(BusinessMembership.user_id == account.id))
    assert membership is not None and membership.business_id == UUID(business_id) and membership.role == "manager"
    events = list((await db_session.scalars(select(AuditEvent))).all())
    assert all(token not in str(event.details) for event in events)
    assert all("new.person@example.test" not in str(event.details) for event in events)


async def test_existing_account_must_sign_in_and_keeps_other_business_access(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    existing = UserAccount(
        email="existing@example.test", display_name="Existing", password_hash=hash_password("existing-passphrase"), active=True,
    )
    other_business = Business(display_name="Other business", industry="general_retail")
    db_session.add_all([existing, other_business]); await db_session.flush()
    existing_id = existing.id
    other_business_id = other_business.id
    db_session.add(BusinessMembership(user_id=existing.id, business_id=other_business.id, role="viewer"))
    await db_session.commit()
    invite = await create_invite(client, business_id, "existing@example.test", "viewer")
    token = invite.json()["token"]
    # The new-account path cannot reset an existing account's password.
    denied = await client.post("/api/v1/invitations/accept/new", headers={"Origin": ORIGIN}, json={
        "token": token, "display_name": "Replacement", "password": "replacement-password",
    })
    assert denied.status_code == 409
    unchanged = await db_session.get(UserAccount, existing_id)
    assert unchanged.password_hash != "replacement-password"
    await client.post("/api/v1/auth/logout")
    login = await client.post("/api/v1/auth/login", json={"email": "existing@example.test", "password": "existing-passphrase"})
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    missing_csrf = await client.post(
        "/api/v1/invitations/accept", headers={"Origin": ORIGIN, "X-CSRF-Token": ""},
        json={"token": token},
    )
    assert missing_csrf.status_code == 403
    accepted = await client.post(
        "/api/v1/invitations/accept", headers={"Origin": ORIGIN}, json={"token": token}
    )
    assert accepted.status_code == 204, accepted.text
    memberships = await current(client)
    ids = {item["business_id"] for item in memberships["businesses"]}
    assert ids == {business_id, str(other_business_id)}


async def test_owner_only_csrf_last_owner_and_self_removal_are_tenant_scoped(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    owner = await db_session.scalar(select(UserAccount).where(UserAccount.email == TEST_OWNER_EMAIL))
    assert owner is not None
    owner_membership = await db_session.scalar(select(BusinessMembership).where(
        BusinessMembership.user_id == owner.id, BusinessMembership.business_id == UUID(business_id),
    ))
    assert owner_membership is not None
    owner_membership_id = owner_membership.id
    owner_id = owner.id
    csrf_missing = await client.patch(
        f"/api/v1/businesses/{business_id}/members/{owner_membership_id}",
        headers={"Origin": ORIGIN, "X-CSRF-Token": ""}, json={"role": "viewer"},
    )
    assert csrf_missing.status_code == 403
    denied = await client.patch(
        f"/api/v1/businesses/{business_id}/members/{owner_membership_id}",
        json={"role": "viewer"},
    )
    assert denied.status_code == 409 and "only owner" in denied.text.lower()
    assert await db_session.scalar(select(BusinessMembership.role).where(
        BusinessMembership.id == owner_membership_id
    )) == "owner"
    last_owner_remove = await client.delete(
        f"/api/v1/businesses/{business_id}/members/{owner_membership_id}",
        headers={"Origin": ORIGIN},
    )
    assert last_owner_remove.status_code == 409

    second = UserAccount(email="second-owner@example.test", display_name="Second", password_hash=hash_password("second-owner-passphrase"), active=True)
    other_business = Business(display_name="Unrelated business", industry="general_retail")
    db_session.add_all([second, other_business]); await db_session.flush()
    other_business_id = other_business.id
    foreign_membership = BusinessMembership(user_id=owner_id, business_id=other_business.id, role="owner")
    db_session.add_all([BusinessMembership(user_id=second.id, business_id=UUID(business_id), role="owner"), foreign_membership])
    await db_session.flush()
    foreign_membership_id = foreign_membership.id
    await db_session.commit()
    foreign_role = await client.patch(
        f"/api/v1/businesses/{business_id}/members/{foreign_membership_id}",
        headers={"Origin": ORIGIN}, json={"role": "viewer"},
    )
    foreign_remove = await client.delete(
        f"/api/v1/businesses/{business_id}/members/{foreign_membership_id}",
        headers={"Origin": ORIGIN},
    )
    assert foreign_role.status_code == 404, foreign_role.text
    assert foreign_remove.status_code == 404, foreign_remove.text
    assert await db_session.scalar(select(BusinessMembership.role).where(
        BusinessMembership.id == foreign_membership_id
    )) == "owner"
    removed = await client.delete(
        f"/api/v1/businesses/{business_id}/members/{owner_membership_id}",
        headers={"Origin": ORIGIN},
    )
    assert removed.status_code == 204
    assert await db_session.scalar(select(UserAccount.active).where(UserAccount.id == owner_id)) is True
    assert await db_session.scalar(select(BusinessMembership.id).where(
        BusinessMembership.user_id == owner_id, BusinessMembership.business_id == UUID(business_id),
    )) is None
    assert await db_session.scalar(select(BusinessMembership.id).where(
        BusinessMembership.user_id == owner_id, BusinessMembership.business_id == other_business_id,
    )) is not None
    assert (await client.get(f"/api/v1/businesses/{business_id}/members")).status_code == 404


async def test_non_owner_cannot_list_or_mutate_team_even_with_tenant_header(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    owner = await db_session.scalar(select(UserAccount).where(UserAccount.email == TEST_OWNER_EMAIL))
    assert owner is not None
    membership = await db_session.scalar(select(BusinessMembership).where(
        BusinessMembership.user_id == owner.id, BusinessMembership.business_id == UUID(business_id),
    ))
    assert membership is not None
    membership.role = "admin"; await db_session.commit()
    current_user = await current(client)
    assert "membership.manage" not in current_user["businesses"][0]["permissions"]
    assert (await client.get(
        f"/api/v1/businesses/{business_id}/members", headers={"X-BudBot-Business-ID": business_id}
    )).status_code == 403
    assert (await create_invite(client, business_id)).status_code == 403


async def test_invitation_revocation_expiry_and_email_collision_are_safe(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    invite = await create_invite(client, business_id)
    token = invite.json()["token"]
    invitation_id = invite.json()["invitation_id"]
    revoked = await client.delete(
        f"/api/v1/businesses/{business_id}/invitations/{invitation_id}", headers={"Origin": ORIGIN}
    )
    assert revoked.status_code == 204
    invalid = await client.post("/api/v1/invitations/inspect", headers={"Origin": ORIGIN}, json={"token": token})
    assert invalid.status_code == 404

    expired = await create_invite(client, business_id, "expired@example.test")
    row = await db_session.get(BusinessInvitation, UUID(expired.json()["invitation_id"]))
    assert row is not None; row.expires_at = utc_now() - timedelta(seconds=1); await db_session.commit()
    expired_check = await client.post("/api/v1/invitations/inspect", headers={"Origin": ORIGIN}, json={"token": expired.json()["token"]})
    assert expired_check.status_code == 404

    # Legacy case variants must fail safely instead of choosing an identity.
    db_session.add_all([
        UserAccount(email="Legacy@example.test", password_hash=hash_password("legacy-passphrase"), active=True),
        UserAccount(email="legacy@EXAMPLE.test", password_hash=hash_password("another-passphrase"), active=True),
    ])
    await db_session.commit()
    collision = await create_invite(client, business_id, "legacy@example.test")
    assert collision.status_code == 201
    failed = await client.post("/api/v1/invitations/accept/new", headers={"Origin": ORIGIN}, json={
        "token": collision.json()["token"], "display_name": "Legacy", "password": "long-enough-passphrase",
    })
    assert failed.status_code == 409 and collision.json()["token"] not in failed.text


async def test_invitation_created_by_removed_owner_is_revoked(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    created = await create_invite(client, business_id, "pending@example.test")
    token = created.json()["token"]
    invitation_id = UUID(created.json()["invitation_id"])
    owner = await db_session.scalar(select(UserAccount).where(UserAccount.email == TEST_OWNER_EMAIL))
    assert owner is not None
    owner_id = owner.id
    owner_membership = await db_session.scalar(select(BusinessMembership).where(
        BusinessMembership.user_id == owner_id, BusinessMembership.business_id == UUID(business_id),
    ))
    assert owner_membership is not None
    membership_id = owner_membership.id
    second = UserAccount(email="backup-owner@example.test", password_hash=hash_password("backup-owner-passphrase"), active=True)
    db_session.add(second); await db_session.flush()
    db_session.add(BusinessMembership(user_id=second.id, business_id=UUID(business_id), role="owner"))
    await db_session.commit()
    removed = await client.delete(
        f"/api/v1/businesses/{business_id}/members/{membership_id}", headers={"Origin": ORIGIN},
    )
    assert removed.status_code == 204
    invite = await db_session.get(BusinessInvitation, invitation_id)
    assert invite is not None and invite.revoked_at is not None
    assert await db_session.scalar(select(AuditEvent.id).where(
        AuditEvent.business_id == UUID(business_id),
        AuditEvent.event_type == "admin.membership.invitation_revoked",
    )) is not None
    check = await client.post("/api/v1/invitations/inspect", headers={"Origin": ORIGIN}, json={"token": token})
    assert check.status_code == 404


async def test_failed_invitation_token_checks_are_rate_limited(team_client):
    client = team_client
    outcomes = []
    for _ in range(31):
        response = await client.post(
            "/api/v1/invitations/inspect", headers={"Origin": ORIGIN},
            json={"token": "invalid-invitation-token-value"},
        )
        outcomes.append(response.status_code)
    assert outcomes == [404] * 30 + [429]
    assert (await client.post(
        "/api/v1/invitations/inspect", headers={"Origin": ORIGIN},
        json={"token": "invalid-invitation-token-value"},
    )).status_code == 429


async def test_activation_rejects_blank_display_name_without_creating_account(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    invitation = await create_invite(client, business_id, "blank-name@example.test")
    response = await client.post(
        "/api/v1/invitations/accept/new", headers={"Origin": ORIGIN}, json={
            "token": invitation.json()["token"], "display_name": "   ",
            "password": "a-safe-new-passphrase",
        },
    )
    assert response.status_code == 422 and "Enter your name" in response.text
    assert await db_session.scalar(select(UserAccount.id).where(
        UserAccount.email == "blank-name@example.test"
    )) is None


async def test_inactive_legacy_account_is_not_activated_by_invitation(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    inactive = UserAccount(
        email="inactive-legacy@example.test", display_name="Legacy",
        password_hash=None, active=False,
    )
    db_session.add(inactive); await db_session.flush()
    inactive_id, inactive_email = inactive.id, inactive.email
    await db_session.commit()
    invitation = await create_invite(client, business_id, inactive_email)
    assert invitation.status_code == 201
    response = await client.post(
        "/api/v1/invitations/accept/new", headers={"Origin": ORIGIN}, json={
            "token": invitation.json()["token"], "display_name": "Legacy User",
            "password": "a-safe-new-passphrase",
        },
    )
    assert response.status_code == 409
    assert await db_session.scalar(select(UserAccount.active).where(UserAccount.id == inactive_id)) is False
    assert await db_session.scalar(select(BusinessMembership.id).where(
        BusinessMembership.user_id == inactive_id, BusinessMembership.business_id == UUID(business_id)
    )) is None


async def test_role_change_and_member_removal_are_audited_and_business_scoped(team_client, db_session):
    client = team_client
    business_id = (await current(client))["businesses"][0]["business_id"]
    member = UserAccount(
        email="team-member@example.test", display_name="Team Member",
        password_hash=hash_password("team-member-passphrase"), active=True,
    )
    db_session.add(member); await db_session.flush()
    membership = BusinessMembership(user_id=member.id, business_id=UUID(business_id), role="viewer")
    db_session.add(membership); await db_session.commit()
    member_id, membership_id = member.id, membership.id

    changed = await client.patch(
        f"/api/v1/businesses/{business_id}/members/{membership_id}",
        headers={"Origin": ORIGIN}, json={"role": "manager"},
    )
    assert changed.status_code == 204
    assert await db_session.scalar(select(BusinessMembership.role).where(
        BusinessMembership.id == membership_id
    )) == "manager"
    removed = await client.delete(
        f"/api/v1/businesses/{business_id}/members/{membership_id}",
        headers={"Origin": ORIGIN},
    )
    assert removed.status_code == 204
    assert await db_session.scalar(select(UserAccount.active).where(UserAccount.id == member_id)) is True
    events = list((await db_session.scalars(
        select(AuditEvent).where(AuditEvent.business_id == UUID(business_id))
    )).all())
    role_event = next(event for event in events if event.event_type == "admin.membership.role_changed")
    removal_event = next(event for event in events if event.event_type == "admin.membership.removed")
    assert role_event.details == {"role": "manager"}
    assert removal_event.resource_id == str(membership_id)


async def test_invitation_attempt_limit_is_shared_by_inspect_and_accept(team_client):
    client = team_client
    for _ in range(29):
        response = await client.post(
            "/api/v1/invitations/inspect", headers={"Origin": ORIGIN},
            json={"token": "invalid-invitation-token-value"},
        )
        assert response.status_code == 404
    # Acceptance shares the same bounded per-IP budget.
    accepted = await client.post(
        "/api/v1/invitations/accept/new", headers={"Origin": ORIGIN},
        json={"token": "invalid-invitation-token-value", "display_name": "Someone", "password": "a-safe-new-passphrase"},
    )
    assert accepted.status_code == 404
    assert (await client.post(
        "/api/v1/invitations/inspect", headers={"Origin": ORIGIN},
        json={"token": "invalid-invitation-token-value"},
    )).status_code == 429
