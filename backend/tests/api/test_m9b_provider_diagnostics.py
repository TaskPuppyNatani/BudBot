"""Saved tenant diagnostics use real transports with deterministic HTTP only."""

import base64
import json
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from budbot.models.auth import AuditEvent
from budbot.models.business import Business
from budbot.models.provider import BusinessAIProfile, ProviderCredential
from budbot.models.session import CustomerSession
from budbot.models.user import BusinessMembership
from budbot.providers.ai.registry import build_ai_provider_registry
from budbot.services.secret_store import EncryptedSecretStore
from budbot.services.provider_service import ProviderService

SECRET = "synthetic-diagnostic-key"
ENDPOINT = "http://provider.test:1234/v1"


@pytest.fixture
async def diagnostics(m2_client, application, db_session):
    settings = application.state.settings
    settings.provider_root_key = SecretStr(base64.urlsafe_b64encode(bytes(range(32))).decode())
    settings.ai_compatible_endpoints = (ENDPOINT,)
    me = (await m2_client.get("/api/v1/auth/me")).json()
    m2_client.headers["X-CSRF-Token"] = me["csrf_token"]
    bid = UUID(me["businesses"][0]["business_id"])
    f = SimpleNamespace(client=m2_client, db=db_session, settings=settings, bid=bid,
        path=f"/api/v1/businesses/{bid}/provider", requests=[], status=200, failure=None, payload=None,
        model_status=200, model_payload=None)

    async def respond(request):
        f.requests.append(request)
        if f.failure:
            raise f.failure
        if request.url.path.endswith("/models"):
            payload = f.model_payload or {"object": "list", "data": [{"id": "operator-model"}]}
            status = f.model_status
        else:
            payload = f.payload
            if payload is None:
                payload = {"content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"} if request.url.path.endswith("/messages") else {
                    "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]}
            status = f.status
        return httpx.Response(status, json=payload, headers={"Location": "https://unapproved.example/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as provider_client:
        application.state.ai_provider_registry = build_ai_provider_registry(provider_client)
        yield f


async def configure(f, provider="openai_compatible", enabled=True, key=False, model="operator-model"):
    body = {"provider": provider, "model": model, "enabled": False,
        "base_url": ENDPOINT if provider == "openai_compatible" else None, "tool_calling": True}
    assert (await f.client.put(f.path, json=body)).status_code == 200
    if key:
        assert (await f.client.put(f.path + "/credential", json={"credential": SECRET})).status_code == 200
    if enabled:
        assert (await f.client.put(f.path, json={**body, "enabled": True})).status_code == 200


async def test_saved_keyless_success_is_bounded_and_does_not_mutate_customer_or_config(diagnostics):
    f = diagnostics
    await configure(f)
    before = (await f.client.get(f.path)).json()
    assert before["runtime_status"] == "ready"
    response = await f.client.post(f.path + "/test", json={})
    assert response.status_code == 200
    assert response.json() == {"code": "AI_CONNECTION_OK", "provider": "openai_compatible", "model": "operator-model"}
    assert response.headers["cache-control"] == "no-store"
    assert (await f.client.get(f.path)).json() == before
    assert await f.db.scalar(select(func.count()).select_from(CustomerSession)) == 0
    model_request, generation_request = f.requests
    assert str(model_request.url) == ENDPOINT + "/models" and model_request.method == "GET"
    assert str(generation_request.url) == ENDPOINT + "/chat/completions"
    assert "authorization" not in model_request.headers
    assert "authorization" not in generation_request.headers
    body = json.loads(generation_request.content)
    assert body == {"model": "operator-model", "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 16}
    assert model_request.extensions["timeout"]["read"] <= 2 and model_request.extensions["timeout"]["connect"] <= 1
    assert generation_request.extensions["timeout"]["read"] <= 10 and generation_request.extensions["timeout"]["connect"] <= 3
    event = await f.db.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.provider.connection_tested"))
    assert event.business_id == f.bid and event.actor_user_id is not None
    expected = {"provider_action": "connection_tested", "provider": "openai_compatible", "success": True, "diagnostic_code": "AI_CONNECTION_OK"}
    assert event.details == expected
    audit = (await f.client.get(f.path.replace("/provider", "/audit"))).json()
    assert next(row["details"] for row in audit["items"] if row["event_type"] == event.event_type) == expected


async def test_advertised_model_must_match_exactly_before_generation(diagnostics):
    f = diagnostics
    await configure(f, model="tpai-ornith-1.5-9b-5")
    f.model_payload = {"object": "list", "data": [{"id": "tpai-ornith-1.5-9b-56"}]}
    result = await f.client.post(f.path + "/test", json={})
    assert result.json()["code"] == "AI_MODEL_UNAVAILABLE"
    assert len(f.requests) == 1 and f.requests[0].url.path == "/v1/models"


async def test_malformed_model_list_is_sanitized_and_stops_generation(diagnostics, caplog):
    f = diagnostics
    await configure(f)
    f.model_payload = {"object": "list", "data": [{"name": SECRET}], "private": SECRET}
    result = await f.client.post(f.path + "/test", json={})
    assert result.json()["code"] == "AI_PROVIDER_BAD_RESPONSE"
    assert len(f.requests) == 1
    assert SECRET not in result.text and SECRET not in caplog.text


@pytest.mark.parametrize("status", [404, 405, 501])
async def test_unsupported_model_discovery_falls_back_to_generation(diagnostics, status):
    f = diagnostics
    await configure(f)
    f.model_status = status
    result = await f.client.post(f.path + "/test", json={})
    assert result.json()["code"] == "AI_CONNECTION_OK"
    assert [request.url.path for request in f.requests] == ["/v1/models", "/v1/chat/completions"]


@pytest.mark.parametrize("provider,url,header", [
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "authorization"),
    ("openai", "https://api.openai.com/v1/chat/completions", "authorization"),
    ("anthropic", "https://api.anthropic.com/v1/messages", "x-api-key"),
    ("openai_compatible", ENDPOINT + "/chat/completions", "authorization"),
])
async def test_each_provider_reuses_its_transport_harness_and_stored_key(diagnostics, provider, url, header):
    f = diagnostics
    await configure(f, provider, key=True)
    credential = await f.db.get(ProviderCredential, f.bid)
    encrypted = credential.encrypted_value
    result = await f.client.post(f.path + "/test")
    assert result.json()["code"] == "AI_CONNECTION_OK" and result.json()["provider"] == provider
    assert set(result.json()) == {"code", "provider", "model"}
    request = f.requests[-1]
    assert str(request.url) == url
    assert request.headers[header] == (SECRET if provider == "anthropic" else "Bearer " + SECRET)
    if provider == "openai_compatible":
        assert f.requests[0].url.path == "/v1/models"
        assert f.requests[0].headers["authorization"] == "Bearer " + SECRET
    body = json.loads(request.content)
    assert body["max_completion_tokens" if provider == "openai" else "max_tokens"] == 16
    assert "tools" not in body and "tool_choice" not in body
    await f.db.refresh(credential)
    assert credential.encrypted_value == encrypted
    assert SECRET not in result.text and SECRET not in (await f.client.get(f.path)).text
    assert SECRET not in (await f.client.get(f.path.replace("/provider", "/audit"))).text


@pytest.mark.parametrize("status,code", [(401, "AI_PROVIDER_AUTH_FAILED"), (403, "AI_PROVIDER_AUTH_FAILED"),
    (404, "AI_MODEL_UNAVAILABLE"), (400, "AI_PROVIDER_BAD_RESPONSE"), (302, "AI_PROVIDER_BAD_RESPONSE"),
    (429, "AI_PROVIDER_UNAVAILABLE"), (503, "AI_PROVIDER_UNAVAILABLE"), (200, "AI_PROVIDER_BAD_RESPONSE")])
async def test_http_failures_are_fixed_codes_without_response_or_secret_material(diagnostics, status, code):
    f = diagnostics
    await configure(f, key=True)
    f.status, f.payload = status, {"error": {"message": SECRET, "authorization": SECRET, "path": "/private/path"}}
    result = await f.client.post(f.path + "/test", json={})
    assert result.status_code == 200 and result.json()["code"] == code
    assert len(f.requests) == 2  # One discovery request and one generation request; no retries.
    assert SECRET not in result.text and "/private/path" not in result.text
    event = await f.db.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.provider.connection_tested"))
    assert event.details["success"] is False and event.details["diagnostic_code"] == code
    assert SECRET not in str(event.details)


@pytest.mark.parametrize("failure,code", [(httpx.ConnectError(SECRET), "AI_PROVIDER_UNREACHABLE"),
    (httpx.ReadTimeout(SECRET), "AI_PROVIDER_TIMEOUT"), (httpx.RemoteProtocolError(SECRET), "AI_PROVIDER_BAD_RESPONSE"),
    (RuntimeError(SECRET), "AI_PROVIDER_ERROR")])
async def test_transport_exceptions_are_sanitized(diagnostics, failure, code):
    f = diagnostics
    await configure(f)
    f.failure = failure
    result = await f.client.post(f.path + "/test", json={})
    assert result.json()["code"] == code and SECRET not in result.text
    assert len(f.requests) == 1


@pytest.mark.parametrize("status", [400, 422])
async def test_structured_model_rejection_is_recognized_without_parsing_error_text(diagnostics, status, caplog):
    f = diagnostics
    await configure(f)
    f.status, f.payload = status, {"error": {"code": "model_not_found", "message": SECRET}}
    response = await f.client.post(f.path + "/test", json={})
    assert response.json()["code"] == "AI_MODEL_UNAVAILABLE"
    assert SECRET not in response.text and SECRET not in caplog.text
    assert len(f.requests) == 2


@pytest.mark.parametrize("state,code", [("missing", "AI_CONFIGURATION_INVALID"), ("disabled", "AI_DISABLED"),
    ("deployment_disabled", "AI_DISABLED"), ("credential_missing", "AI_CREDENTIAL_MISSING"),
    ("denied", "AI_ENDPOINT_DENIED"), ("broken_secret", "AI_CONFIGURATION_INVALID")])
async def test_preflight_prevents_network_and_global_fallback(diagnostics, state, code):
    f = diagnostics
    if state != "missing":
        await configure(f, enabled=state != "disabled", key=state == "broken_secret")
    else:
        f.settings.ai_enabled = True
        f.settings.ai_api_key = SecretStr(SECRET)
        f.settings.ai_model = "global-model-must-not-be-used"
    if state == "deployment_disabled":
        f.settings.ai_tenant_enabled = False
    elif state == "credential_missing":
        profile = await f.db.get(BusinessAIProfile, f.bid)
        profile.provider, profile.base_url = "openai", None
        await f.db.commit()
    elif state == "denied":
        f.settings.ai_compatible_endpoints = ()
    elif state == "broken_secret":
        credential = await f.db.get(ProviderCredential, f.bid)
        credential.encrypted_value = b"synthetic-corrupt-ciphertext"
        await f.db.commit()
    result = await f.client.post(f.path + "/test", json={})
    assert result.json()["code"] == code and f.requests == []
    assert SECRET not in result.text
    status = (await f.client.get(f.path)).json()
    assert status["runtime_status"] == ("disabled" if code == "AI_DISABLED" else "ready" if state == "broken_secret" else "incomplete")


async def test_allowlist_blocks_before_decryption_and_overrides_cannot_be_supplied(diagnostics):
    f = diagnostics
    await configure(f, key=True)
    for body in [{"url": "http://unapproved.example/"}, {"model": "different"}, {"credential": SECRET}, ["test"]]:
        response = await f.client.post(f.path + "/test", json=body)
        assert response.status_code == 422 and SECRET not in response.text
    f.settings.ai_compatible_endpoints = ()
    with patch.object(EncryptedSecretStore, "open", side_effect=AssertionError("must not decrypt")):
        assert (await f.client.post(f.path + "/test", json={})).json()["code"] == "AI_ENDPOINT_DENIED"
    assert f.requests == []


async def test_disappearing_tenant_profile_cannot_switch_to_legacy_credentials(diagnostics):
    f = diagnostics
    await configure(f)
    profile = await f.db.get(BusinessAIProfile, f.bid)
    f.settings.ai_enabled, f.settings.ai_model = True, "legacy-model"
    f.settings.ai_base_url, f.settings.ai_api_key = ENDPOINT, SecretStr(SECRET)
    f.settings.ai_legacy_business_id = f.bid
    # A profile can disappear between preflight and runtime resolution. Even an
    # explicitly bound legacy tenant must not test with process credentials.
    with patch.object(ProviderService, "_profile", new=AsyncMock(side_effect=[profile, None])):
        response = await f.client.post(f.path + "/test", json={})
    assert response.json()["code"] == "AI_CONFIGURATION_INVALID"
    assert f.requests == [] and SECRET not in response.text


@pytest.mark.parametrize("role", ["admin", "manager", "viewer", "unknown"])
async def test_non_owner_is_denied(diagnostics, role):
    f = diagnostics
    member = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == f.bid))
    member.role = role
    await f.db.commit()
    assert (await f.client.post(f.path + "/test", json={})).status_code == 403
    assert f.requests == []


@pytest.mark.parametrize("failure,expected", [("anonymous", 401), ("csrf_missing", 403), ("csrf_invalid", 403), ("foreign", 404)])
async def test_auth_csrf_and_tenant_header_cannot_bypass_membership(diagnostics, failure, expected):
    f = diagnostics
    await configure(f)
    path = f.path + "/test"
    if failure == "anonymous":
        f.client.cookies.clear()
    elif failure == "csrf_missing":
        f.client.headers.pop("X-CSRF-Token")
    elif failure == "csrf_invalid":
        f.client.headers["X-CSRF-Token"] = "invalid"
    else:
        foreign = Business(display_name="Foreign", industry="general_retail")
        f.db.add(foreign)
        await f.db.commit()
        path = path.replace(str(f.bid), str(foreign.id))
    response = await f.client.post(path, json={}, headers={"X-BudBot-Business-ID": str(f.bid)})
    assert response.status_code == expected and f.requests == []
    assert await f.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "admin.provider.connection_tested")) == 0
