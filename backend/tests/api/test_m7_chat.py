"""Public M7 chat API trust-boundary and lifecycle tests."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from budbot.core.config import Settings
from budbot.core.tenancy import TenantContext
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.models.location import Location, LocationHours
from budbot.providers.ai.base import AIFinishReason, AIResponse, AIToolCall
from budbot.providers.ai.harness_registry import build_ai_harness_registry
from budbot.providers.ai.mock import MockAIProvider
from budbot.providers.ai.registry import AIProviderRegistry
from budbot.schemas.session import CustomerSessionCreate
from budbot.services.session_service import SessionService


async def _seed(db_session, *, name: str = "API Shop"):
    business = Business(display_name=name, industry="retail")
    assistant = AssistantConfiguration(
        display_name="API Helper",
        greeting="Hello",
        fallback_message="I cannot verify that.",
        business=business,
    )
    location = Location(
        business=business,
        display_name=f"{name} Main",
        address_line_1="10 Main St",
        city="Portland",
        region="Oregon",
        region_code="OR",
        postal_code="97201",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add_all([business, assistant, location])
    await db_session.flush()
    db_session.add(
        LocationHours(
            business_id=business.id,
            location_id=location.id,
            day_of_week=0,
            open_time=time(9, 0),
            close_time=time(18, 0),
            is_closed=False,
        )
    )
    await db_session.flush()
    tenant = TenantContext(business.id)
    customer_session = await SessionService(db_session, tenant).create(
        CustomerSessionCreate(selected_location_id=location.id)
    )
    return tenant, business, location, customer_session


def _response(*, content: str | None = None, call: AIToolCall | None = None) -> AIResponse:
    calls = (call,) if call is not None else ()
    return AIResponse(
        content=content,
        finish_reason=(AIFinishReason.TOOL_CALLS if calls else AIFinishReason.STOP),
        tool_calls=calls,
        provider="mock",
        model="api-test-model",
        harness="generic_openai",
    )


def _install_mock_runtime(
    application: FastAPI,
    *responses: AIResponse,
    api_key: str | None = None,
) -> MockAIProvider:
    application.state.settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+asyncpg://budbot:test@localhost:5432/budbot_test",
        ai_enabled=True,
        ai_provider="mock",
        ai_model="api-test-model",
        ai_harness="generic_openai",
        ai_api_key=api_key,
        ai_capability_tool_calling=True,
    )
    provider = MockAIProvider(responses)
    registry = AIProviderRegistry()
    registry.register("mock", provider)
    application.state.ai_provider_registry = registry
    application.state.ai_harness_registry = build_ai_harness_registry()
    return provider


async def test_chat_endpoint_returns_only_normalized_content_and_tool_result_stays_data(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session,
) -> None:
    tenant, _business, _location, customer_session = await _seed(db_session)
    secret = "private-api-secret"
    provider = _install_mock_runtime(
        application,
        _response(call=AIToolCall("call_1", "list_locations", {})),
        _response(content=f"The location is listed. {secret}"),
        api_key=secret,
    )

    response = await m2_client.post(
        "/api/v1/chat",
        headers={"X-BudBot-Business-ID": str(tenant.business_id)},
        json={"session_id": str(customer_session.id), "message": "Where are you?"},
    )

    assert response.status_code == 200
    customer_content = response.json()["content"]
    assert customer_content.startswith("Active locations:")
    assert "API Shop Main" in customer_content
    assert "The location is listed." not in customer_content
    assert secret not in customer_content
    tool_message = next(
        message
        for message in provider.requests[1].messages
        if message.role.value == "tool"
    )
    assert "API Shop Main" in tool_message.content
    assert provider.requests[0].messages[0].role.value == "system"
    assert provider.requests[0].messages[-1].role.value == "user"
    assert secret not in " ".join(message.content for request in provider.requests for message in request.messages)


async def test_public_chat_cannot_override_provider_model_harness_url_or_credentials(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session,
) -> None:
    tenant, _business, _location, customer_session = await _seed(db_session)
    provider = _install_mock_runtime(application)
    response = await m2_client.post(
        "/api/v1/chat",
        headers={"X-BudBot-Business-ID": str(tenant.business_id)},
        json={
            "session_id": str(customer_session.id),
            "message": "Hello",
            "provider": "openai",
            "model": "attacker-model",
            "harness": "arbitrary.module:Class",
            "base_url": "http://169.254.169.254/latest/meta-data",
            "api_key": "attacker-secret",
        },
    )
    assert response.status_code == 422
    assert not provider.requests


async def test_chat_rejects_invalid_messages_and_unknown_sessions(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session,
) -> None:
    tenant, _business, _location, customer_session = await _seed(db_session)
    _install_mock_runtime(application, _response(content="safe"))
    headers = {"X-BudBot-Business-ID": str(tenant.business_id)}

    blank = await m2_client.post(
        "/api/v1/chat",
        headers=headers,
        json={"session_id": str(customer_session.id), "message": "   "},
    )
    missing = await m2_client.post(
        "/api/v1/chat",
        headers=headers,
        json={"session_id": str(uuid4()), "message": "Hello"},
    )
    assert blank.status_code == 422
    assert missing.status_code == 404
    assert missing.json()["code"] == "SESSION_NOT_FOUND"


async def test_wrong_tenant_and_expired_sessions_fail_before_provider_call(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session,
) -> None:
    tenant, _business, _location, customer_session = await _seed(db_session)
    provider = _install_mock_runtime(application, _response(content="safe"))
    wrong_tenant = await m2_client.post(
        "/api/v1/chat",
        headers={"X-BudBot-Business-ID": str(uuid4())},
        json={"session_id": str(customer_session.id), "message": "Hello"},
    )
    customer_session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()
    expired = await m2_client.post(
        "/api/v1/chat",
        headers={"X-BudBot-Business-ID": str(tenant.business_id)},
        json={"session_id": str(customer_session.id), "message": "Hello"},
    )
    assert wrong_tenant.status_code == 404
    assert expired.status_code == 410
    assert expired.json()["code"] == "SESSION_EXPIRED"
    assert not provider.requests


async def test_ai_provider_outage_does_not_disable_commands_health_or_readiness(
    m2_client: AsyncClient,
    application: FastAPI,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, _business, _location, customer_session = await _seed(db_session)
    provider = _install_mock_runtime(application)

    async def ready_without_external_ai(_timeout: float) -> None:
        return None

    monkeypatch.setattr(application.state.database, "ping", ready_without_external_ai)
    chat = await m2_client.post(
        "/api/v1/chat",
        headers={"X-BudBot-Business-ID": str(tenant.business_id)},
        json={"session_id": str(customer_session.id), "message": "Hello"},
    )
    command = await m2_client.post(
        "/api/v1/commands/execute",
        headers={"X-BudBot-Business-ID": str(tenant.business_id)},
        json={"session_id": str(customer_session.id), "input": "/hours"},
    )
    health = await m2_client.get("/health")
    ready = await m2_client.get("/ready")

    assert chat.status_code == 503
    assert chat.json()["code"] == "AI_PROVIDER_UNAVAILABLE"
    assert "secret" not in chat.text.lower()
    assert command.status_code == 200
    assert "Monday" in command.json()["output"]
    assert health.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok"}
    assert len(provider.requests) == 1
