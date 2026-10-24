"""Pass 2 FAQ administration, customer resolution and safe audit history."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from budbot.services import admin_actions
from budbot.core.security import token_digest
from budbot.core.time import utc_now
from budbot.models.auth import AdminSession, AuditEvent
from budbot.models.business import Business
from budbot.models.knowledge import FAQEntry
from budbot.models.location import Location
from budbot.models.user import BusinessMembership, UserAccount


@pytest.fixture
async def faq_admin(m2_client, db_session):
    me = (await m2_client.get("/api/v1/auth/me")).json()
    m2_client.headers["X-CSRF-Token"] = me["csrf_token"]
    bid = UUID(me["businesses"][0]["business_id"])
    foreign = Business(display_name="Other tenant", industry="general_retail")
    db_session.add(foreign)
    await db_session.flush()
    locations = [Location(
        business_id=tenant, display_name="Main", address_line_1="10 Main",
        city="Portland", region="Oregon", region_code="OR", postal_code="97201",
        country="US", timezone="America/Los_Angeles", active=True,
    ) for tenant in (bid, foreign.id)]
    db_session.add_all(locations)
    await db_session.flush()
    private = FAQEntry(business_id=foreign.id, question="Foreign private question", answer="Foreign private answer")
    db_session.add(private)
    await db_session.commit()
    return SimpleNamespace(
        client=m2_client, db=db_session, bid=str(bid), base=f"/api/v1/businesses/{bid}",
        location=str(locations[0].id), foreign_location=str(locations[1].id),
        foreign=str(foreign.id), private=str(private.id), user=me["user"]["id"],
    )


async def create(f, **values):
    return await f.client.post(f.base + "/faqs", json={"question": "Parking?", "answer": "Use the main lot.", **values})


async def test_faq_crud_states_and_metadata_only_audit(faq_admin):
    f = faq_admin
    assert (await f.client.get(f.base + "/faqs")).json() == []
    added = await create(f, question="  Private question marker?  ", answer="  Private answer marker.  ", location_id=f.location)
    assert added.status_code == 201, added.text
    entry = added.json()
    assert entry["question"] == "Private question marker?"
    assert entry["answer"] == "Private answer marker."
    assert entry["business_id"] == f.bid and entry["location_id"] == f.location
    assert (await f.client.get(f.base + "/faqs")).json() == [entry]
    changed = await f.client.patch(f.base + f"/faqs/{entry['id']}", json={
        "answer": "Updated private answer.", "enabled": False, "is_public": False, "location_id": None,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["location_id"] is None
    assert not changed.json()["enabled"] and not changed.json()["is_public"]
    history = (await f.client.get(f.base + "/audit")).json()["items"]
    assert {event["event_type"] for event in history} == {"admin.faq.created", "admin.faq.updated"}
    for event in history:
        assert event["resource_type"] == "faq" and event["resource_id"] == entry["id"]
        assert event["actor_user_id"] == f.user and event["business_id"] == f.bid
        assert set(event["details"]) == {"location_id", "enabled", "is_public", "changed_fields"}
    assert "Private question marker" not in json.dumps(history)
    assert "Private answer marker" not in json.dumps(history)
    assert "Updated private answer" not in json.dumps(history)
    # Disable/re-enable is the removal contract; no destructive route exists.
    assert (await f.client.delete(f.base + f"/faqs/{entry['id']}")).status_code == 405


@pytest.mark.parametrize("role,read,write,audit", [
    ("owner", 200, 201, 200), ("admin", 200, 201, 403),
    ("manager", 200, 403, 403), ("viewer", 200, 403, 403), ("unknown", 403, 403, 403),
])
async def test_central_role_policy(faq_admin, role, read, write, audit):
    f = faq_admin
    membership = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == UUID(f.bid)))
    membership.role = role
    await f.db.commit()
    assert (await f.client.get(f.base + "/faqs")).status_code == read
    assert (await create(f)).status_code == write
    assert (await f.client.get(f.base + "/audit")).status_code == audit
    if write == 403:
        assert (await f.client.patch(f.base + f"/faqs/{f.private}", json={"enabled": False})).status_code == 403


async def test_cross_tenant_faq_audit_and_location_are_indistinguishable_from_missing(faq_admin):
    f = faq_admin
    for foreign in (f.foreign, str(uuid4())):
        base = f"/api/v1/businesses/{foreign}"
        for suffix in ("/faqs", "/audit"):
            assert (await f.client.get(base + suffix, headers={"X-BudBot-Business-ID": f.bid})).status_code == 404
        assert (await f.client.post(base + "/faqs", json={"question": "X", "answer": "Y"})).status_code == 404
        assert (await f.client.patch(base + f"/faqs/{f.private}", json={"answer": "Takeover"})).status_code == 404
    for entry_id in (f.private, str(uuid4())):
        denied = await f.client.patch(f.base + f"/faqs/{entry_id}", json={"answer": "Takeover"})
        assert denied.status_code == 404 and denied.json()["code"] == "FAQ_NOT_FOUND"
    entry = (await create(f)).json()
    for location_id in (f.foreign_location, str(uuid4())):
        assert (await create(f, location_id=location_id)).status_code == 404
        response = await f.client.patch(f.base + f"/faqs/{entry['id']}", json={"location_id": location_id})
        assert response.status_code == 404 and response.json()["code"] == "LOCATION_NOT_FOUND"
    assert "Foreign private" not in (await f.client.get(f.base + "/faqs")).text


async def test_multi_business_member_still_uses_path_scope_not_selector(faq_admin):
    f = faq_admin
    f.db.add(BusinessMembership(user_id=UUID(f.user), business_id=UUID(f.foreign), role="owner"))
    f.db.add(AuditEvent(business_id=UUID(f.foreign), event_type="admin.business.created"))
    await f.db.commit()
    local = (await create(f)).json()
    other_base = f"/api/v1/businesses/{f.foreign}"
    foreign = await f.client.get(other_base + "/faqs", headers={"X-BudBot-Business-ID": f.bid})
    assert [item["id"] for item in foreign.json()] == [f.private]
    own = await f.client.get(f.base + "/faqs", headers={"X-BudBot-Business-ID": f.foreign})
    assert [item["id"] for item in own.json()] == [local["id"]]
    assert (await f.client.patch(f.base + f"/faqs/{f.private}", json={"answer": "Wrong scope"})).status_code == 404
    for base, bid in ((f.base, f.bid), (other_base, f.foreign)):
        history = (await f.client.get(base + "/audit")).json()["items"]
        assert len(history) == 1 and history[0]["business_id"] == bid


@pytest.mark.parametrize("failure", ["no_cookie", "missing_csrf", "bad_csrf", "expired", "revoked", "inactive", "no_membership"])
async def test_authentication_membership_and_csrf_cannot_be_bypassed_by_selector(faq_admin, failure):
    f = faq_admin
    entry = (await create(f)).json()
    expected = 401
    if failure == "no_cookie":
        f.client.cookies.clear()
    elif failure in ("missing_csrf", "bad_csrf"):
        f.client.headers.pop("X-CSRF-Token", None)
        if failure == "bad_csrf":
            f.client.headers["X-CSRF-Token"] = "invalid"
        expected = 403
    elif failure in ("expired", "revoked"):
        record = await f.db.scalar(select(AdminSession).where(AdminSession.token_digest == token_digest(f.client.cookies.get("budbot_admin_session"))))
        if failure == "expired":
            record.expires_at = utc_now() - timedelta(seconds=1)
        else:
            record.revoked_at = utc_now()
        await f.db.commit()
    elif failure == "inactive":
        user = await f.db.get(UserAccount, UUID(f.user))
        user.active = False
        await f.db.commit()
    else:
        membership = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == UUID(f.bid)))
        await f.db.delete(membership)
        await f.db.commit()
        expected = 404
    for method, suffix, payload in (("POST", "/faqs", {"question": "Q", "answer": "A"}),
                                     ("PATCH", f"/faqs/{entry['id']}", {"enabled": False})):
        result = await f.client.request(method, f.base + suffix, json=payload, headers={"X-BudBot-Business-ID": f.bid})
        assert result.status_code == expected, result.text
    if expected != 403:
        for suffix in ("/faqs", "/audit"):
            assert (await f.client.get(f.base + suffix, headers={"X-BudBot-Business-ID": f.bid})).status_code == expected


async def test_normalized_duplicates_rejected_when_public_and_scope_matches(faq_admin):
    f = faq_admin
    assert (await create(f)).status_code == 201
    assert (await create(f, question=" \tPARKING? \n")).status_code == 409
    local = await create(f, question="parking?", location_id=f.location)
    assert local.status_code == 201  # Intended business/location override.
    assert (await create(f, question="PARKING?", location_id=f.location)).status_code == 409
    private = await create(f, question="parking?", is_public=False)
    disabled = await create(f, question="parking?", enabled=False)
    assert private.status_code == disabled.status_code == 201
    for entry, patch in ((private.json(), {"is_public": True}), (disabled.json(), {"enabled": True}),
                         (local.json(), {"location_id": None})):
        rejected = await f.client.patch(f.base + f"/faqs/{entry['id']}", json=patch)
        assert rejected.status_code == 409 and rejected.json()["code"] == "FAQ_DUPLICATE"
    history = (await f.client.get(f.base + "/audit")).json()["items"]
    assert len(history) == 4 and all(event["event_type"] == "admin.faq.created" for event in history)
    assert len((await f.client.get(f.base + "/faqs")).json()) == 4


@pytest.mark.parametrize("payload", [
    {"question": " "}, {"question": "x" * 501}, {"answer": " "}, {"answer": "x" * 10001},
    {"location_id": "bad-uuid"}, {"business_id": str(uuid4())},
])
async def test_faq_input_bounds_and_mass_assignment(faq_admin, payload):
    assert (await create(faq_admin, **payload)).status_code == 422
    assert (await faq_admin.client.get(faq_admin.base + "/faqs")).json() == []
    assert (await faq_admin.client.get(faq_admin.base + "/audit")).json()["items"] == []


@pytest.mark.parametrize("patch", [{}, {"question": None}, {"answer": None}, {"enabled": None}, {"is_public": None}, {"business_id": str(uuid4())}])
async def test_invalid_patch_cannot_change_state(faq_admin, patch):
    f = faq_admin
    entry = (await create(f)).json()
    assert (await f.client.patch(f.base + f"/faqs/{entry['id']}", json=patch)).status_code == 422
    assert (await f.client.get(f.base + "/faqs")).json() == [entry]
    assert (await f.client.patch(f.base + "/faqs/bad-uuid", json={"enabled": False})).status_code == 422


async def test_customer_faq_resolution_tracks_admin_edits_without_admin_auth(faq_admin):
    f = faq_admin
    global_entry = (await create(f)).json()
    local = (await create(f, question="PARKING?", answer="Use the local lot.", location_id=f.location)).json()
    # Keep the admin cookie for writes, but use a distinct anonymous customer client.
    from httpx import AsyncClient
    async with AsyncClient(transport=f.client._transport, base_url="http://testserver", headers={"X-BudBot-Business-ID": f.bid}) as customer:
        sessions = [(await customer.post("/api/v1/sessions", json=payload)).json()["id"] for payload in ({}, {"selected_location_id": f.location})]

        async def lookup(session_id, expected=200):
            result = await customer.post("/api/v1/commands/execute", json={"session_id": session_id, "input": "/faq parking?"})
            assert result.status_code == expected, result.text
            if expected == 404:
                assert result.json()["code"] == "FAQ_NOT_FOUND"
            return result.text

        assert "Use the main lot." in await lookup(sessions[0])
        assert "Use the local lot." in await lookup(sessions[1])
        assert (await f.client.patch(f.base + f"/faqs/{local['id']}", json={"answer": "Updated local lot."})).status_code == 200
        assert "Updated local lot." in await lookup(sessions[1])
        assert (await f.client.patch(f.base + f"/faqs/{local['id']}", json={"enabled": False})).status_code == 200
        assert "Use the main lot." in await lookup(sessions[1])
        assert (await f.client.patch(f.base + f"/faqs/{global_entry['id']}", json={"is_public": False})).status_code == 200
        assert "Use the main lot." not in await lookup(sessions[0], 404)
        assert "Use the local lot." not in await lookup(sessions[1], 404)
        assert (await customer.get(f.base + "/faqs")).status_code == 401


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("failure", ["audit", "response", "commit"])
async def test_failed_publication_rolls_back_faq_and_success_event(faq_admin, monkeypatch, operation, failure):
    f = faq_admin
    entry = (await create(f)).json() if operation == "update" else None
    before = (await f.client.get(f.base + "/faqs")).json()
    history = (await f.client.get(f.base + "/audit")).json()
    original = admin_actions.record_audit_event

    async def fail_after_audit(*args, **kwargs):
        await original(*args, **kwargs)
        raise HTTPException(status_code=503, detail="Synthetic audit failure.")

    def fail_response(_entry):
        raise HTTPException(status_code=503, detail="Synthetic response failure.")

    async def fail_commit():
        raise HTTPException(status_code=503, detail="Synthetic commit failure.")

    with monkeypatch.context() as patch:
        if failure == "audit":
            patch.setattr(admin_actions, "record_audit_event", fail_after_audit)
        elif failure == "response":
            patch.setattr(admin_actions.FAQRead, "model_validate", fail_response)
        else:
            patch.setattr(f.db, "commit", fail_commit)
        result = await create(f) if entry is None else await f.client.patch(f.base + f"/faqs/{entry['id']}", json={"answer": "Must roll back"})
    assert result.status_code == 503
    assert (await f.client.get(f.base + "/faqs")).json() == before
    assert (await f.client.get(f.base + "/audit")).json() == history


async def test_audit_history_order_pagination_redaction_and_tenant_scope(faq_admin):
    f = faq_admin
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for index in (1, 2, 3):
        f.db.add(AuditEvent(
            id=UUID(int=index), business_id=UUID(f.bid), event_type="admin.faq.updated",
            resource_type="faq", resource_id=str(uuid4()), created_at=now + timedelta(seconds=index // 3),
            details={"password": "private-marker", "token": "private-marker", "csrf": "private-marker",
                     "note": "private-marker", "nested": {"secret": "private-marker"},
                     "answer": "private-marker", "changed_fields": "question,answer,private-marker",
                     "enabled": True, "is_public": False, "location_id": f.location},
        ))
    f.db.add_all([AuditEvent(business_id=UUID(f.foreign), event_type="foreign-private-event"),
                     AuditEvent(business_id=None, event_type="global-private-event")])
    await f.db.commit()
    first = await f.client.get(f.base + "/audit?limit=2&offset=0")
    assert first.status_code == 200
    data = first.json()
    assert [item["id"] for item in data["items"]] == [str(UUID(int=3)), str(UUID(int=2))]
    assert data["next_offset"] == 2
    assert data["items"][0]["details"] == {"enabled": True, "is_public": False, "location_id": f.location, "changed_fields": "answer,question"}
    second = (await f.client.get(f.base + "/audit?limit=2&offset=2")).json()
    assert [item["id"] for item in second["items"]] == [str(UUID(int=1))]
    assert second["next_offset"] is None
    assert "private" not in first.text and "private" not in json.dumps(second)
    assert (await f.client.get(f.base + "/audit?offset=10000")).json() == {"items": [], "next_offset": None}


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=-1", "limit=bad", "limit=1.5", "offset=-1", "offset=10001", "offset=bad"])
async def test_audit_query_bounds(faq_admin, query):
    assert (await faq_admin.client.get(faq_admin.base + f"/audit?{query}")).status_code == 422
