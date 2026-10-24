"""Authenticated command transport, service/audit parity and customer separation."""

import base64
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from budbot.models.assistant import AssistantConfiguration
from budbot.models.auth import AdminSession, AuditEvent
from budbot.models.business import Business
from budbot.models.knowledge import FAQEntry
from budbot.models.location import Location
from budbot.models.session import CustomerSession
from budbot.models.user import BusinessMembership
from budbot.providers.ai.registry import build_ai_provider_registry
from budbot.schemas.provider import ProviderConnectionRead, ProviderDiagnosticCode
from budbot.services.business_service import BusinessService
from budbot.services.provider_service import ProviderService

NAMES = {"help", "status", "locations", "location", "hours", "set-hours", "bot-name", "greeting", "faq", "add-faq", "disable", "enable", "provider", "test", "preview", "compliance", "audit"}
SECRET = "synthetic-command-provider-key"
ENDPOINT = "http://approved-provider.test/v1"


@pytest.fixture
async def admin(m2_client, application, db_session):
    me = (await m2_client.get("/api/v1/auth/me")).json()
    m2_client.headers["X-CSRF-Token"] = me["csrf_token"]
    bid = UUID(me["businesses"][0]["business_id"])
    foreign = Business(display_name="Foreign business", industry="general_retail",
        assistant_configuration=AssistantConfiguration(display_name="Foreign assistant", greeting="Foreign greeting", fallback_message="Ask staff"))
    db_session.add(foreign)
    await db_session.flush()
    locations = [Location(business_id=business_id, display_name="Main", address_line_1="10 Main",
        city="Portland", region="Oregon", region_code="OR", country="US", postal_code="97201", timezone="UTC")
        for business_id in (bid, foreign.id)]
    db_session.add_all(locations)
    await db_session.commit()
    f = SimpleNamespace(client=m2_client, db=db_session, app=application, bid=bid,
        base=f"/api/v1/businesses/{bid}", location=str(locations[0].id), foreign=str(foreign.id),
        foreign_location=str(locations[1].id), user=UUID(me["user"]["id"]), requests=[])
    settings = application.state.settings
    settings.provider_root_key = SecretStr(base64.urlsafe_b64encode(bytes(range(32))).decode())
    settings.ai_compatible_endpoints = (ENDPOINT,)

    async def respond(request):
        f.requests.append(request)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "exact-model"}]} if request.method == "GET" else {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as provider_client:
        application.state.ai_provider_registry = build_ai_provider_registry(provider_client)
        yield f


async def command(f, value, location=None, **extra):
    return await f.client.post(f.base + "/commands/execute", json={"input": value, "location_id": location, **extra})


async def execute(f, value, location=None):
    response = await command(f, value, location)
    assert response.status_code == 200, response.text
    return response.json()


async def test_all_seventeen_commands_use_existing_scoped_services(admin):
    f = admin
    metadata = await f.client.get(f.base + "/commands")
    assert {item["name"] for item in metadata.json()} == NAMES
    help_result = await execute(f, "/HELP")
    assert {item["name"] for item in help_result["commands"]} == NAMES
    assert '/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed' in help_result["output"]
    assert '/add-faq Do you have parking? | Street parking only.' in help_result["output"]
    assert not any(value in help_result["output"] for value in ('JSON', 'day_of_week', 'location_id', 'UUID'))
    assert "Test Assistant" in (await execute(f, "/status"))["output"]
    listed = (await execute(f, "/locations"))["output"]
    assert "Main — Active" in listed and f.location not in listed
    assert (await execute(f, "/location"))["location_id"] is None
    assert (await execute(f, "/location main"))["location_id"] == f.location
    assert (await execute(f, "/location " + f.location))["location_id"] == f.location
    assert "not configured" in (await execute(f, "/hours", f.location))["output"]
    assert "Monday: 9:00 AM" in (await execute(f, "/set-hours monday 9am 5pm", f.location))["output"]
    await execute(f, "/set-hours tuesday closed", f.location)
    location = (await f.client.get(f.base + "/locations/" + f.location)).json()
    assert location["hours"][0]["open_time"] == "09:00:00"
    assert "Location name" in (await execute(f, "/bot-name Location name", f.location))["output"]
    assert "Local greeting" in (await execute(f, "/greeting Local greeting", f.location))["output"]
    effective = (await f.client.get(f.base + f"/locations/{f.location}/effective-assistant")).json()
    assert effective["display_name"] == "Location name" and effective["greeting"] == "Local greeting"
    assert (await f.client.get(f.base + "/assistant")).json()["display_name"] == "Test Assistant"
    assert "No matching FAQs" in (await execute(f, "/faq"))["output"]
    assert "FAQ added for Main" in (await execute(f, "/add-faq Parking? | Verified lot.", f.location))["output"]
    assert "Verified lot" in (await execute(f, "/faq parking", f.location))["output"]
    assert (await f.client.get(f.base + "/faqs")).json()[0]["location_id"] == f.location
    await execute(f, "/disable", f.location)
    assert not (await f.client.get(f.base + f"/locations/{f.location}/effective-assistant")).json()["enabled"]
    await execute(f, "/enable", f.location)
    assert (await f.client.get(f.base + f"/locations/{f.location}/effective-assistant")).json()["enabled"]
    assert (await execute(f, "/location --business", f.location))["location_id"] is None
    assert "Not set up" in (await execute(f, "/provider"))["output"]
    assert "AI setup needs attention" in (await execute(f, "/test"))["output"]
    preview = await execute(f, "/preview")
    assert preview["preview_url"] == f"/widget/?business_id={f.bid}"
    assert "Age check: Not required" in (await execute(f, "/compliance"))["output"]
    assert "Rules for Main" in (await execute(f, "/compliance", f.location))["output"]
    assert "FAQ added" in (await execute(f, "/audit 50"))["output"]
    assert await f.db.scalar(select(func.count()).select_from(CustomerSession)) == 0


async def test_business_confirmation_and_assistant_identity_are_preserved(admin):
    f = admin
    before = (await f.client.get(f.base + "/assistant")).json()
    response = await command(f, "/disable")
    assert response.status_code == 409 and response.json()["code"] == "COMMAND_CONFIRMATION_REQUIRED"
    assert (await f.client.get(f.base + "/assistant")).json() == before
    await execute(f, "/disable --confirm")
    assert not (await f.client.get(f.base + "/assistant")).json()["enabled"]
    await execute(f, "/enable")
    await execute(f, "/bot-name New business name")
    await execute(f, "/greeting New business greeting")
    after = (await f.client.get(f.base + "/assistant")).json()
    assert after["id"] == before["id"] and after["enabled"]
    assert after["display_name"] == "New business name" and after["greeting"] == "New business greeting"
    assert "New business name" in (await execute(f, "/bot-name"))["output"]
    assert "New business greeting" in (await execute(f, "/greeting"))["output"]


async def test_repeated_friendly_hours_edits_preserve_other_days_and_use_same_audit(admin):
    f = admin
    await execute(f, "/set-hours tues 10:00 18:00", f.location)
    await execute(f, "/set-hours monday 9am 10pm", f.location)
    await execute(f, "/set-hours mon 10am 9pm", f.location)
    rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
    assert {row["day_of_week"]: (row["open_time"], row["close_time"]) for row in rows} == {0: ("10:00:00", "21:00:00"), 1: ("10:00:00", "18:00:00")}
    output = (await execute(f, "/set-hours monday closed", f.location))["output"]
    assert "Monday: Closed" in output and "Tuesday: 10:00 AM–6:00 PM" in output
    rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
    assert len(rows) == 2 and rows[0]["is_closed"] and rows[0]["open_time"] is None
    before = (await f.client.get(f.base + "/audit")).json()
    failure = await command(f, "/set-hours monday 10pm 9am", f.location)
    assert failure.status_code == 422 and "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" in failure.json()["detail"]
    assert (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"] == rows
    assert (await f.client.get(f.base + "/audit")).json() == before
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.location.updated"))).all())
    assert len(events) == 4 and all(event.details == {"changed_fields": "hours"} for event in events)


async def test_bulk_hours_preserve_unnamed_days_repeat_and_audit_once_per_edit(admin):
    f = admin
    def schedule(rows):
        return [(row["day_of_week"], row["open_time"], row["close_time"], row["is_closed"]) for row in rows]
    await execute(f, "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed", f.location)
    rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
    assert len(rows) == 7
    assert all((row["open_time"], row["close_time"]) == ("09:00:00", "21:00:00") for row in rows[:5])
    weekend = schedule(rows[5:])
    assert weekend == [(5, "10:00:00", "20:00:00", False), (6, None, None, True)]
    for value in ("weekdays 8am-6pm", "monday-friday 9:00am-9 pm"):
        await execute(f, "/set-hours " + value, f.location)
        rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
        assert len(rows) == 7 and schedule(rows[5:]) == weekend
    assert all(row["open_time"] == "09:00:00" and row["close_time"] == "21:00:00" for row in rows[:5])
    weekdays = schedule(rows[:5])
    output = (await execute(f, "/set-hours weekends closed", f.location))["output"]
    rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
    assert schedule(rows[:5]) == weekdays and all(row["is_closed"] for row in rows[5:])
    assert "Saturday: Closed" in output and "Sunday: Closed" in output
    for group in ("everyday", "daily"):
        await execute(f, "/set-hours " + group + " 10am-8pm", f.location)
        rows = (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"]
        assert len(rows) == 7 and all(row["open_time"] == "10:00:00" and row["close_time"] == "20:00:00" for row in rows)
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.location.updated"))).all())
    assert len(events) == 6
    assert all(event.details == {"changed_fields": "hours"} and event.actor_user_id == f.user
        and event.resource_id == f.location and event.business_id == f.bid for event in events)


@pytest.mark.parametrize("value,detail", [
    ("mon-fri 8am-6pm; saturday 10am-25:00", "I couldn't understand those hours"),
    ("mon-fri 8am-6pm; weekends 8pm-10am", "I couldn't understand those hours"),
    ("mon-fri 8am-6pm; fri closed", "Friday appears more than once"),
    ("everyday closed; weekends 10am-8pm", "Saturday appears more than once"),
    ("weekdays closed; sun closed; sunday closed", "Sunday appears more than once"),
])
async def test_invalid_bulk_hours_leave_existing_week_and_audit_unchanged(admin, value, detail):
    f = admin
    await execute(f, "/set-hours everyday 9am-5pm", f.location)
    before = (await f.client.get(f.base + "/locations/" + f.location)).json()
    audit_before = (await f.client.get(f.base + "/audit")).json()
    response = await command(f, "/set-hours " + value, f.location)
    assert response.status_code == 422 and detail in response.json()["detail"]
    assert "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" in response.json()["detail"]
    assert not any(word in response.text for word in ("LocationUpdate", "day_of_week", "Traceback", SECRET))
    assert (await f.client.get(f.base + "/locations/" + f.location)).json() == before
    assert (await f.client.get(f.base + "/audit")).json() == audit_before


async def test_friendly_faq_uses_current_scope_and_first_pipe_only(admin):
    f = admin
    business_result = await execute(f, "/add-faq Do you deliver? | Ask the store.")
    local_result = await execute(f, "/add-faq Do you have parking? | Street parking only. | Ask staff for help.", f.location)
    assert business_result["output"] == "FAQ added for all locations."
    assert local_result["output"] == "FAQ added for Main."
    rows = (await f.client.get(f.base + "/faqs")).json()
    by_question = {row["question"]: row for row in rows}
    assert by_question["Do you deliver?"]["location_id"] is None
    assert by_question["Do you have parking?"]["location_id"] == f.location
    assert by_question["Do you have parking?"]["answer"] == "Street parking only. | Ask staff for help."
    assert all(row["enabled"] and row["is_public"] for row in rows)
    output = (await execute(f, "/faq", f.location))["output"]
    assert "All locations" in output and "Main" in output and "Visible to customers" in output
    assert not any(value in output for value in (f.location, "location_id", "scope=", "True"))


async def test_normal_locations_hide_ids_and_duplicate_names_have_advanced_fallback(admin):
    f = admin
    assert f.location not in (await execute(f, "/locations"))["output"]
    assert f.location not in (await execute(f, "/location Main"))["output"]
    assert f.location not in (await execute(f, "/location", f.location))["output"]
    duplicate = Location(business_id=f.bid, display_name="  MAIN  ", address_line_1="20 Second",
        city="Portland", region="Oregon", region_code="OR", country="US", postal_code="97201", timezone="UTC", active=False)
    f.db.add(duplicate)
    await f.db.commit()
    duplicate_id = str(duplicate.id)
    listed = (await execute(f, "/locations"))["output"]
    assert "Inactive" in listed and "20 Second" in listed
    assert f.location in listed and duplicate_id in listed
    ambiguous = await command(f, "/location main")
    assert ambiguous.status_code == 409 and "menu" in ambiguous.json()["detail"]
    assert (await execute(f, "/location " + duplicate_id))["location_id"] == duplicate_id


@pytest.mark.parametrize("code", list(ProviderDiagnosticCode))
async def test_owner_test_results_are_plain_english_while_audit_keeps_stable_codes(admin, code):
    f = admin
    diagnostic = ProviderConnectionRead(code=code, provider="openai_compatible", model="saved-model")
    with patch.object(ProviderService, "test_connection", return_value=diagnostic):
        output = (await execute(f, "/test"))["output"]
    assert "AI_" not in output and "openai_compatible" not in output
    assert "LM Studio / OpenAI-compatible" in output and "saved-model" in output
    expected = {
        ProviderDiagnosticCode.OK: "Connected",
        ProviderDiagnosticCode.UNREACHABLE: "Could not reach the AI provider.",
        ProviderDiagnosticCode.MODEL_UNAVAILABLE: "The configured AI model could not be found.",
    }.get(code)
    if expected:
        assert output.startswith(expected)
    event = await f.db.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.provider.connection_tested"))
    assert event.details["diagnostic_code"] == code.value
    assert event.details["success"] == (code == ProviderDiagnosticCode.OK)


async def test_owner_audit_is_readable_sanitized_and_keeps_requested_count(admin):
    f = admin
    from datetime import timedelta
    from budbot.core.time import utc_now
    now = utc_now()
    f.db.add_all([
        AuditEvent(business_id=f.bid, event_type="admin.provider.connection_tested", created_at=now, details={
            "provider_action": "connection_tested", "provider": "openai_compatible",
            "diagnostic_code": "AI_MODEL_UNAVAILABLE", "success": False, "credential": SECRET}),
        AuditEvent(business_id=f.bid, event_type="admin.faq.created", created_at=now - timedelta(seconds=1), details={
            "location_id": f.location, "changed_fields": "question,answer", "enabled": True, "is_public": True, "response": SECRET}),
        AuditEvent(business_id=f.bid, event_type=SECRET, created_at=now - timedelta(seconds=2), details={"ciphertext": SECRET}),
    ])
    await f.db.commit()
    before = (await f.client.get(f.base + "/audit")).json()
    output = (await execute(f, "/audit 2"))["output"]
    assert "AI connection checked" in output and "The configured AI model could not be found" in output
    assert "FAQ added" in output and "For: Main" in output and "Visible to customers" in output
    assert not any(value in output for value in (SECRET, f.location, "AI_MODEL_UNAVAILABLE", "admin.", "diagnostic_code", "{", "}"))
    assert output.count("UTC —") == 2
    assert "Settings updated" in (await execute(f, "/audit 3"))["output"]
    assert (await f.client.get(f.base + "/audit")).json() == before


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "viewer", "unknown"])
async def test_help_and_actions_use_current_central_role_policy(admin, role):
    f = admin
    member = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == f.bid))
    member.role = role
    await f.db.commit()
    metadata = await f.client.get(f.base + "/commands")
    if role == "unknown":
        assert metadata.status_code == 403
        assert (await command(f, "/help")).status_code == 403
        return
    names = {item["name"] for item in metadata.json()}
    assert ("set-hours" in names) == (role in {"owner", "admin", "manager"})
    assert ("add-faq" in names) == (role in {"owner", "admin"})
    assert ("disable" in names) == (role in {"owner", "admin"})
    for name in ("provider", "test", "audit"):
        assert (name in names) == (role == "owner")
        assert (await command(f, "/" + name)).status_code == (200 if role == "owner" else 403)
    assert (await command(f, "/bot-name")).status_code == 200
    assert (await command(f, "/bot-name Updated")).status_code == (200 if role in {"owner", "admin"} else 403)
    assert (await command(f, '/set-hours weekdays 9am-9pm; weekends closed', f.location)).status_code == (200 if role in {"owner", "admin", "manager"} else 403)


@pytest.mark.parametrize("state,expected", [("anonymous", 401), ("csrf_missing", 403), ("csrf_bad", 403), ("inactive_user", 401), ("revoked", 401), ("expired", 401), ("inactive_business", 404), ("membership_removed", 404)])
async def test_auth_session_membership_and_csrf_required(admin, state, expected):
    f = admin
    if state == "anonymous":
        f.client.cookies.clear()
    elif state == "csrf_missing":
        f.client.headers.pop("X-CSRF-Token")
    elif state == "csrf_bad":
        f.client.headers["X-CSRF-Token"] = SECRET
    elif state == "inactive_user":
        from budbot.models.user import UserAccount
        (await f.db.get(UserAccount, f.user)).active = False
    elif state == "revoked":
        from budbot.core.time import utc_now
        (await f.db.scalar(select(AdminSession).where(AdminSession.user_id == f.user))).revoked_at = utc_now()
    elif state == "expired":
        from datetime import timedelta
        from budbot.core.time import utc_now
        (await f.db.scalar(select(AdminSession).where(AdminSession.user_id == f.user))).expires_at = utc_now() - timedelta(seconds=1)
    elif state == "inactive_business":
        (await f.db.get(Business, f.bid)).active = False
    else:
        await f.db.delete(await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == f.bid)))
    await f.db.commit()
    assert (await command(f, "/status")).status_code == expected
    assert (await command(f, "/set-hours weekdays 9am-9pm; weekends closed", f.location)).status_code == expected
    if state in {"anonymous", "inactive_user", "revoked", "expired"}:
        assert (await f.client.get(f.base + "/commands")).status_code == expected


async def test_tenant_path_location_and_memberships_cannot_be_spoofed(admin):
    f = admin
    assert (await f.client.post(f.base.replace(str(f.bid), f.foreign) + "/commands/execute",
        json={"input": "/status"}, headers={"X-BudBot-Business-ID": str(f.bid)})).status_code == 404
    assert (await command(f, "/status", f.foreign_location)).status_code == 404
    assert (await command(f, "/location " + f.foreign_location)).status_code == 404
    assert (await command(f, '/add-faq Q | A', f.foreign_location)).status_code == 404
    assert (await command(f, '/set-hours weekdays 9am-9pm', f.foreign_location)).status_code == 404
    f.db.add(BusinessMembership(user_id=f.user, business_id=UUID(f.foreign), role="viewer"))
    await f.db.commit()
    foreign_base = f.base.replace(str(f.bid), f.foreign)
    read = await f.client.post(foreign_base + "/commands/execute", json={"input": "/status"}, headers={"X-BudBot-Business-ID": str(f.bid)})
    assert read.status_code == 200 and "Foreign assistant" in read.json()["output"]
    assert (await f.client.post(foreign_base + "/commands/execute", json={"input": "/bot-name Stolen"})).status_code == 403
    assert "Foreign assistant" not in (await execute(f, "/status"))["output"]


@pytest.mark.parametrize("value", [
    '/set-hours monday 10pm 9am', '/set-hours flurday 9am 5pm',
    '/set-hours monday 25:00 26:00', '/set-hours monday closed extra',
    '/set-hours {"hours":[],"active":false}', '/add-faq Question without answer',
    '/add-faq | No question', '/add-faq No answer |', '/add-faq missing separator ' + SECRET,
    '/add-faq ' + 'q' * 501 + ' | Answer', '/add-faq Question | ' + 'a' * 10001,
    '/bot-name ' + 'x' * 201, '/greeting ' + 'x' * 1001,
])
async def test_mutation_validation_does_not_partially_write_or_audit(admin, value):
    f = admin
    before = (await f.client.get(f.base + "/assistant")).json()
    count = await f.db.scalar(select(func.count()).select_from(AuditEvent))
    response = await command(f, value, f.location)
    assert response.status_code == 422 and SECRET not in response.text
    if value.startswith("/set-hours"):
        assert "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" in response.json()["detail"]
    elif value.startswith("/add-faq"):
        assert "/add-faq Do you have parking? | Street parking only." in response.json()["detail"]
    assert (await f.client.get(f.base + "/assistant")).json() == before
    assert (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"] == []
    assert await f.db.scalar(select(func.count()).select_from(FAQEntry)) == 0
    assert await f.db.scalar(select(func.count()).select_from(AuditEvent)) == count


async def test_audit_parity_with_dashboard_and_no_duplicate_events(admin):
    f = admin
    await f.client.patch(f.base + "/assistant", json={"display_name": "From dashboard"})
    await execute(f, "/bot-name From command")
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.assistant.updated"))).all())
    assert len(events) == 2 and events[0].details == events[1].details == {"changed_fields": "display_name"}
    assert events[0].resource_id == events[1].resource_id and all(event.actor_user_id == f.user for event in events)
    await f.client.patch(f.base + "/locations/" + f.location, json={"hours": []})
    await execute(f, '/set-hours monday closed', f.location)
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.location.updated"))).all())
    assert len(events) == 2 and events[0].details == events[1].details == {"changed_fields": "hours"}
    faq = {"question": "Private marker", "answer": "Private answer", "location_id": None}
    assert (await f.client.post(f.base + "/faqs", json=faq)).status_code == 201
    await execute(f, "/add-faq Different marker | Private answer")
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.faq.created"))).all())
    assert len(events) == 2 and events[0].details == events[1].details
    assert "Private marker" not in (await execute(f, "/audit 50"))["output"]


async def test_faq_command_reuses_duplicate_validation_without_partial_publication(admin):
    f = admin
    value = '/add-faq Parking? | Verified lot.'
    await execute(f, value)
    before = (await f.client.get(f.base + "/audit")).json()
    response = await command(f, value.replace("Parking?", "  parking?  "))
    assert response.status_code == 409 and response.json()["code"] == "FAQ_DUPLICATE"
    assert len((await f.client.get(f.base + "/faqs")).json()) == 1
    assert (await f.client.get(f.base + "/audit")).json() == before


async def test_provider_test_reuses_sealed_path_and_never_exposes_credentials(admin):
    f = admin
    body = {"provider": "openai_compatible", "base_url": ENDPOINT, "model": "exact-model", "enabled": False, "tool_calling": True}
    assert (await f.client.put(f.base + "/provider", json=body)).status_code == 200
    assert (await f.client.put(f.base + "/provider/credential", json={"credential": SECRET})).status_code == 200
    assert (await f.client.put(f.base + "/provider", json={**body, "enabled": True})).status_code == 200
    before = (await f.client.get(f.base + "/provider")).json()
    f.db.add(AuditEvent(business_id=f.bid, event_type="admin.legacy", details={
        "credential": SECRET, "authorization": SECRET, "ciphertext": SECRET,
        "response": SECRET, "stack_trace": SECRET, "model": SECRET}))
    await f.db.commit()
    for value in ("/provider", "/status", "/test", "/audit 50"):
        output = (await execute(f, value))["output"]
        assert not any(private in output for private in (SECRET, "openai_compatible", "AI_CONNECTION_OK", "runtime_status", "True", "False"))
        if value in {"/provider", "/status"}:
            assert "Settings complete" in output
    assert [request.url.path for request in f.requests] == ["/v1/models", "/v1/chat/completions"]
    assert all(request.headers["authorization"] == "Bearer " + SECRET for request in f.requests)
    assert (await f.client.get(f.base + "/provider")).json() == before
    event = await f.db.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.provider.connection_tested"))
    assert event.details == {"provider_action": "connection_tested", "provider": "openai_compatible", "success": True, "diagnostic_code": "AI_CONNECTION_OK"}
    f.app.state.settings.ai_compatible_endpoints = ()
    f.requests.clear()
    assert "not approved for this installation" in (await execute(f, "/test"))["output"]
    assert f.requests == []


@pytest.mark.parametrize("operation", ["assistant", "hours", "bulk_hours", "faq", "test"])
async def test_shared_action_audit_failure_rolls_back_command_state(admin, operation):
    f = admin
    from budbot.services import admin_actions
    before_assistant = (await f.client.get(f.base + "/assistant")).json()
    before_audit = (await f.client.get(f.base + "/audit")).json()
    value, location = {
        "assistant": ("/bot-name Must roll back", None),
        "hours": ('/set-hours monday closed', f.location),
        "bulk_hours": ('/set-hours mon-fri 9am-9pm; weekends closed', f.location),
        "faq": ('/add-faq Q | A', None),
        "test": ("/test", None),
    }[operation]
    original = admin_actions.record_audit_event

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError(SECRET)

    with patch.object(admin_actions, "record_audit_event", side_effect=fail):
        response = await command(f, value, location)
    assert response.status_code == 500 and SECRET not in response.text
    assert (await f.client.get(f.base + "/assistant")).json() == before_assistant
    assert (await f.client.get(f.base + "/locations/" + f.location)).json()["hours"] == []
    assert (await f.client.get(f.base + "/faqs")).json() == []
    assert (await f.client.get(f.base + "/audit")).json() == before_audit


async def test_admin_compliance_and_enable_never_bypass_customer_age_checks(admin):
    f = admin
    business = await f.db.get(Business, f.bid)
    business.compliance_domain, business.compliance_profile_id = "cannabis", "oregon_cannabis"
    await f.db.commit()
    assert "Age check: Required (21+)" in (await execute(f, "/compliance", f.location))["output"]
    await execute(f, "/enable")
    assert (await command(f, "/compliance disable")).status_code == 400
    f.client.cookies.clear()
    headers = {"X-BudBot-Business-ID": str(f.bid)}
    session = await f.client.post("/api/v1/sessions", headers=headers, json={})
    session_id = session.json()["id"]
    assert (await f.client.patch(f"/api/v1/sessions/{session_id}/location", headers=headers,
        json={"selected_location_id": f.location})).status_code == 200
    blocked = await f.client.post("/api/v1/commands/execute", headers=headers, json={"session_id": session_id, "input": "/products"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "AGE_VERIFICATION_REQUIRED"


async def test_safe_errors_and_no_transport_overrides(admin):
    f = admin
    for extra in ({"authenticated_admin": True}, {"business_id": f.foreign}, {"permissions": ["provider.write"]}, {"scope": "customer"}):
        assert (await command(f, "/help", **extra)).status_code == 422
    assert (await command(f, "/provider " + SECRET)).status_code == 400
    with patch.object(BusinessService, "get", side_effect=RuntimeError(SECRET)):
        response = await command(f, "/status")
    assert response.status_code == 500 and response.json()["code"] == "COMMAND_FAILED"
    assert SECRET not in response.text and "Traceback" not in response.text
    assert (await command(f, "/unknown-private-command")).status_code == 404
    assert (await command(f, "/compliance update " + SECRET)).status_code == 400
    for value in ("/audit 0", "/audit 51", "/audit invalid", "/status extra"):
        assert (await command(f, value)).status_code == 400


async def test_customer_command_transport_stays_public_and_cannot_execute_admin_actions(admin):
    f = admin
    f.client.cookies.clear()
    session = await f.client.post("/api/v1/sessions", headers={"X-BudBot-Business-ID": str(f.bid)}, json={})
    assert session.status_code == 201
    payload = {"session_id": session.json()["id"], "input": "/help"}
    help_result = await f.client.post("/api/v1/commands/execute", headers={"X-BudBot-Business-ID": str(f.bid)}, json=payload)
    assert help_result.status_code == 200
    assert not {"set-hours", "add-faq", "provider", "test", "audit"} & {item["name"] for item in help_result.json()["commands"]}
    for value in ("/set-hours", "/add-faq", "/provider", "/audit"):
        denied = await f.client.post("/api/v1/commands/execute", headers={"X-BudBot-Business-ID": str(f.bid)}, json={**payload, "input": value})
        assert denied.status_code == 403
    assert (await command(f, "/help")).status_code == 401
