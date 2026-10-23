"""Diagnostic resource bounds and normalized transport behavior."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from budbot.providers.ai.base import AIProviderConfig, AIResponse, AIFinishReason, AIToolCall, AICapabilities
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.harness_registry import build_ai_harness_registry
from budbot.providers.ai.registry import AIProviderRegistry
from budbot.schemas.provider import ProviderDiagnosticCode as Code
from budbot.services.provider_diagnostics import diagnose_connection
from budbot.services.audit_service import audit_details_for_read


def setup():
    config = AIProviderConfig(provider="openai_compatible", model="chosen-model", harness="generic_openai",
        base_url="https://approved.example/v1", capabilities=AICapabilities(tool_calling=True))
    providers = AIProviderRegistry()
    transport = AsyncMock()
    transport.generate.return_value = AIResponse("OK", AIFinishReason.STOP, (), config.provider, config.model, config.harness)
    providers.register(config.provider, transport)
    return config, providers, transport


async def test_transport_request_is_tiny_and_unsolicited_tools_are_never_executed():
    config, providers, transport = setup()
    assert await diagnose_connection(config, providers, build_ai_harness_registry()) == Code.OK
    request, bounded, harness = transport.generate.call_args.args
    assert not request.tools and request.model == config.model
    assert request.generation.max_output_tokens == bounded.max_output_tokens == 16
    assert bounded.timeout_seconds == 10 and bounded.connect_timeout_seconds == 3
    assert harness.key == config.harness
    transport.generate.return_value = AIResponse(None, AIFinishReason.TOOL_CALLS,
        (AIToolCall("call1", "get_hours", {}),), config.provider, config.model, config.harness)
    assert await diagnose_connection(config, providers, build_ai_harness_registry()) == Code.INCOMPATIBLE_RESPONSE


async def test_outer_timeout_bounds_even_a_transport_that_ignores_its_timeout(monkeypatch):
    config, providers, transport = setup()
    async def stuck(*args):
        await asyncio.Event().wait()
    transport.generate.side_effect = stuck
    monkeypatch.setattr("budbot.services.provider_diagnostics.TEST_TIMEOUT_SECONDS", 0.01)
    assert await diagnose_connection(config, providers, build_ai_harness_registry()) == Code.TIMEOUT
    assert transport.generate.call_count == 1


@pytest.mark.parametrize("error", [AIError("unknown-private-error"), AIError("AI_CONNECTION_OK"), RuntimeError("private marker")])
async def test_unknown_exceptions_never_become_success_or_disclose_text(error):
    config, providers, transport = setup()
    transport.generate.side_effect = error
    assert await diagnose_connection(config, providers, build_ai_harness_registry()) == Code.PROVIDER_ERROR


def test_audit_read_projection_allows_only_known_provider_test_metadata():
    assert audit_details_for_read({"provider_action": "connection_tested", "provider": "openrouter",
        "diagnostic_code": "AI_PROVIDER_AUTH_FAILED", "success": False, "model": "private marker",
        "endpoint": "private marker", "response": "private marker", "credential": "private marker"}) == {
            "provider_action": "connection_tested", "provider": "openrouter", "diagnostic_code": "AI_PROVIDER_AUTH_FAILED", "success": False}
    assert audit_details_for_read({"provider_action": "connection_tested", "provider": "private marker",
        "diagnostic_code": "private marker", "success": "private marker"}) == {"provider_action": "connection_tested"}
