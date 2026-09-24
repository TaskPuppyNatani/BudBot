"""Provider-neutral M7 value and contract tests."""

from dataclasses import FrozenInstanceError

import pytest

from budbot.providers.ai.base import (
    AIFinishReason,
    AICapabilities,
    AIMessage,
    AIMessageRole,
    AIRequest,
    AIResponse,
    AIToolCall,
    AIToolDefinition,
    AIUsage,
)


def test_normalized_request_response_messages_tools_and_usage() -> None:
    call = AIToolCall("call_1", "get_hours", {"day": "Monday"})
    request = AIRequest(
        messages=(
            AIMessage(AIMessageRole.SYSTEM, "Use verified tools."),
            AIMessage(AIMessageRole.USER, "When do you close?"),
            AIMessage(AIMessageRole.ASSISTANT, tool_calls=(call,)),
            AIMessage(AIMessageRole.TOOL, '{"result":"6 PM"}', name="get_hours", tool_call_id="call_1"),
        ),
        model="operator-selected-model",
        harness="generic_openai",
        tools=(
            AIToolDefinition(
                "get_hours",
                "Read configured hours.",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
        ),
    )
    response = AIResponse(
        content=None,
        finish_reason=AIFinishReason.TOOL_CALLS,
        tool_calls=(call,),
        provider="openai_compatible",
        model=request.model,
        harness=request.harness,
        usage=AIUsage(input_tokens=10, output_tokens=4, total_tokens=14),
        request_id=request.request_id,
    )

    assert request.messages[0].role is AIMessageRole.SYSTEM
    assert request.messages[1].role is AIMessageRole.USER
    assert request.messages[3].role is AIMessageRole.TOOL
    assert request.messages[3].tool_call_id == "call_1"
    assert request.tools[0].name == "get_hours"
    assert response.tool_calls[0].arguments["day"] == "Monday"
    assert response.usage == AIUsage(10, 4, 14)
    with pytest.raises(FrozenInstanceError):
        request.model = "other"  # type: ignore[misc]


def test_core_types_reject_invalid_roles_tool_messages_and_usage() -> None:
    with pytest.raises(ValueError, match="tool messages require"):
        AIMessage(AIMessageRole.TOOL, "result")
    with pytest.raises(ValueError, match="only assistant"):
        AIMessage(AIMessageRole.USER, "user", tool_calls=(AIToolCall("c1", "get_hours", {}),))
    with pytest.raises(ValueError, match="nonnegative integers"):
        AIUsage(input_tokens=-1)
    with pytest.raises(ValueError, match="nonnegative integers"):
        AIUsage(input_tokens=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="JSON-compatible"):
        AIToolCall("c1", "get_hours", {"bad": object()})  # type: ignore[dict-item]


def test_capabilities_are_explicit_and_tool_calls_require_consistency() -> None:
    capabilities = AICapabilities(tool_calling=False, usage_reporting=True)
    assert capabilities.text_generation is True
    assert capabilities.tool_calling is False
    assert capabilities.usage_reporting is True
    with pytest.raises(ValueError, match="tool calls"):
        AIResponse(
            content="text",
            finish_reason=AIFinishReason.STOP,
            tool_calls=(AIToolCall("c1", "get_hours", {}),),
            provider="mock",
            model="test-model",
            harness="generic_openai",
        )
