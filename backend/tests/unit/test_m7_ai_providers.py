"""Deterministic provider-transport and model-harness contract tests."""

import json

import httpx
import pytest

from budbot.providers.ai.base import (
    AICapabilities,
    AIMessage,
    AIMessageRole,
    AIProviderConfig,
    AIRequest,
    AIToolDefinition,
)
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.harness_registry import (
    AIHarnessRegistry,
    build_ai_harness_registry,
)
from budbot.providers.ai.harnesses import (
    AnthropicNativeHarness,
    OpenAIChatHarness,
    QwenOpenAIHarness,
)
from budbot.providers.ai.mock import MockAIProvider
from budbot.providers.ai.openai_compatible import OpenAICompatibleTransport
from budbot.providers.ai.registry import AIProviderRegistry, build_ai_provider_registry


def _config(
    *,
    provider: str = "openai_compatible",
    harness: str = "generic_openai",
    base_url: str | None = "http://local-model:1234/v1",
    api_key: str | None = None,
    usage: bool = True,
    tools: bool = True,
) -> AIProviderConfig:
    return AIProviderConfig(
        provider=provider,
        model="operator-selected-model",
        harness=harness,
        base_url=base_url,
        api_key=api_key,
        capabilities=AICapabilities(
            tool_calling=tools,
            usage_reporting=usage,
            temperature=True,
            max_output_tokens=True,
            system_role=True,
        ),
    )


def _request(*, tools: tuple[AIToolDefinition, ...] = ()) -> AIRequest:
    return AIRequest(
        messages=(
            AIMessage(AIMessageRole.SYSTEM, "Use only verified tools."),
            AIMessage(AIMessageRole.USER, "What time do you close?"),
        ),
        model="operator-selected-model",
        harness="generic_openai",
        tools=tools,
    )


def _tool() -> AIToolDefinition:
    return AIToolDefinition(
        "get_hours",
        "Read configured hours.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )


async def test_generic_openai_transport_uses_trusted_url_model_and_no_auth_by_default() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "6 PM"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleTransport(client)
        request = _request()
        response = await provider.generate(
            request, _config(), OpenAIChatHarness()
        )

    assert seen["url"] == "http://local-model:1234/v1/chat/completions"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["model"] == "operator-selected-model"
    assert seen["body"]["max_tokens"] == 800
    assert response.content == "6 PM"
    assert response.usage is not None
    assert response.usage.total_tokens == 10


async def test_compatible_transport_normalizes_tool_calls_and_optional_auth() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        body = json.loads(request.content)
        seen["tool"] = body["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_hours",
                            "type": "function",
                            "function": {"name": "get_hours", "arguments": "{}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleTransport(client)
        response = await provider.generate(
            _request(tools=(_tool(),)),
            _config(api_key="local-secret"),
            OpenAIChatHarness(),
        )

    assert seen["authorization"] == "Bearer local-secret"
    assert seen["tool"] == "get_hours"
    assert response.tool_calls[0].name == "get_hours"
    assert dict(response.tool_calls[0].arguments) == {}


async def test_openai_cloud_adapter_reuses_transport_with_cloud_auth_and_native_limit_field() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "openai_call_hours",
                            "type": "function",
                            "function": {"name": "get_hours", "arguments": "{}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = build_ai_provider_registry(client)
        provider = registry.resolve("openai")
        config = _config(
            provider="openai",
            harness="openai_chat",
            base_url=None,
            api_key="hosted-secret",
            usage=True,
        )
        response = await provider.generate(
            _request(tools=(_tool(),)),
            config,
            build_ai_harness_registry().resolve("openai_chat"),
        )

    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer hosted-secret"
    assert seen["body"]["max_completion_tokens"] == 800
    assert response.provider == "openai"
    assert response.tool_calls[0].name == "get_hours"
    assert response.usage is not None
    assert response.usage.total_tokens == 9


async def test_anthropic_native_request_and_tool_response_normalization() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_hours",
                    "name": "get_hours",
                    "input": {},
                }],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )

    request = AIRequest(
        messages=(
            AIMessage(AIMessageRole.SYSTEM, "Trusted rules"),
            AIMessage(AIMessageRole.USER, "When do you close?"),
        ),
        model="operator-selected-model",
        harness="anthropic_native",
        tools=(_tool(),),
    )
    config = _config(
        provider="anthropic",
        harness="anthropic_native",
        base_url=None,
        api_key="anthropic-secret",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_ai_provider_registry(client).resolve("anthropic")
        response = await provider.generate(request, config, AnthropicNativeHarness())

    assert seen["path"] == "/v1/messages"
    assert seen["auth"] == "anthropic-secret"
    assert seen["version"] == "2023-06-01"
    assert seen["body"]["system"] == "Trusted rules"
    assert seen["body"]["tools"][0]["input_schema"]["type"] == "object"
    assert response.tool_calls[0].id == "toolu_hours"
    assert response.usage is not None
    assert response.usage.input_tokens == 12


def test_anthropic_harness_keeps_tool_results_structurally_separate() -> None:
    request = AIRequest(
        messages=(
            AIMessage(AIMessageRole.TOOL, "{\"result\":\"6 PM\"}", name="get_hours", tool_call_id="toolu_hours"),
        ),
        model="model",
        harness="anthropic_native",
    )
    body = AnthropicNativeHarness().encode_request(
        request,
        _config(provider="anthropic", harness="anthropic_native", base_url=None, api_key="x"),
    )
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"][0]["type"] == "tool_result"


def test_qwen_harness_discards_hidden_reasoning_and_normalizes_visible_content() -> None:
    request = _request()
    config = _config(harness="qwen_openai")
    response = QwenOpenAIHarness().decode_response(
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "reasoning_content": "private reasoning",
                    "content": "<think>private reasoning</think>Verified answer",
                },
                "finish_reason": "stop",
            }]
        },
        request,
        config,
    )
    assert response.content == "Verified answer"
    assert "private reasoning" not in (response.content or "")


def test_qwen_harness_strips_repeated_reasoning_blocks_and_preserves_visible_text() -> None:
    response = QwenOpenAIHarness().decode_response(
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": (
                        "Visible before <think>private one</think> "
                        "middle <think>private two</think> visible after"
                    ),
                },
                "finish_reason": "stop",
            }]
        },
        _request(),
        _config(harness="qwen_openai"),
    )
    assert response.content == "Visible before middle visible after"
    assert "private" not in (response.content or "")


@pytest.mark.parametrize(
    "content",
    [
        "</think><think>reasoning",  # reversed and unmatched
        "<think>reasoning",  # opening delimiter without close
        "reasoning</think>",  # closing delimiter without open
        "<think>outer <think>inner</think> tail</think>visible",  # nested
        "</think><think>first</think><think>partial",  # mismatched ordering
    ],
)
def test_qwen_harness_rejects_malformed_reasoning_delimiters(content: str) -> None:
    with pytest.raises(AIError) as error:
        QwenOpenAIHarness().decode_response(
            {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }]
            },
            _request(),
            _config(harness="qwen_openai"),
        )
    assert error.value.code == "AI_PROVIDER_BAD_RESPONSE"


def test_qwen_malformed_reasoning_cannot_become_a_tool_call() -> None:
    with pytest.raises(AIError) as error:
        QwenOpenAIHarness().decode_response(
            {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "<think>private reasoning without a close",
                        "tool_calls": [{
                            "id": "call_hours",
                            "type": "function",
                            "function": {"name": "get_hours", "arguments": "{}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }]
            },
            _request(tools=(_tool(),)),
            _config(harness="qwen_openai"),
        )
    assert error.value.code == "AI_PROVIDER_BAD_RESPONSE"


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"unexpected": true}',
        b'{"choices":[{"message":{"content":"x"},"finish_reason":{}}]}',
        b'{"choices":[{"message":{"content":"x"},"finish_reason":"stop"}],"usage":{"prompt_tokens":-1}}',
        b'{"choices":[{"message":{"tool_calls":[{"id":"call_1","function":{"name":"get_hours","arguments":"not-json"}}]},"finish_reason":"tool_calls"}]}',
    ],
)
async def test_malformed_upstream_responses_are_normalized(body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body))
    ) as client:
        provider = OpenAICompatibleTransport(client)
        with pytest.raises(AIError) as error:
            await provider.generate(_request(), _config(), OpenAIChatHarness())
    assert error.value.code == "AI_PROVIDER_BAD_RESPONSE"
    assert "not-json" not in error.value.detail


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, text="Bearer secret-value"), "AI_PROVIDER_AUTH_FAILED"),
        (httpx.Response(429, text="secret-value"), "AI_PROVIDER_UNAVAILABLE"),
        (httpx.Response(503, text="secret-value"), "AI_PROVIDER_UNAVAILABLE"),
        (httpx.Response(404, text="secret-value"), "AI_MODEL_UNAVAILABLE"),
    ],
)
async def test_provider_http_failures_are_safe_and_never_echo_response_body(
    response: httpx.Response, expected: str
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        provider = OpenAICompatibleTransport(client)
        with pytest.raises(AIError) as error:
            await provider.generate(
                _request(), _config(api_key="secret-value"), OpenAIChatHarness()
            )
    assert error.value.code == expected
    assert "secret-value" not in str(error.value)


async def test_timeout_and_unreachable_provider_are_normalized() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret diagnostic")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AIError) as error:
            await OpenAICompatibleTransport(client).generate(
                _request(), _config(), OpenAIChatHarness()
            )
    assert error.value.code == "AI_PROVIDER_TIMEOUT"

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret diagnostic", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        with pytest.raises(AIError) as error:
            await OpenAICompatibleTransport(client).generate(
                _request(), _config(), OpenAIChatHarness()
            )
    assert error.value.code == "AI_PROVIDER_UNAVAILABLE"


async def test_provider_and_harness_registries_are_explicit_and_reject_unknown_keys() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        providers = build_ai_provider_registry(client)
        assert {"openai_compatible", "openai", "anthropic"} == set(providers._providers)
        with pytest.raises(AIError) as provider_error:
            providers.resolve("os.system")
    assert provider_error.value.code == "AI_PROVIDER_UNKNOWN"
    with pytest.raises(AIError) as mock_error:
        providers.resolve("mock")
    assert mock_error.value.code == "AI_PROVIDER_UNKNOWN"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        injected_mock = MockAIProvider()
        test_providers = build_ai_provider_registry(client, mock_provider=injected_mock)
        assert test_providers.resolve("mock") is injected_mock

    harnesses = build_ai_harness_registry()
    assert {"generic_openai", "qwen_openai", "openai_chat", "anthropic_native"} == set(harnesses._harnesses)
    with pytest.raises(AIError) as harness_error:
        harnesses.resolve("some.module:Class")
    assert harness_error.value.code == "AI_HARNESS_UNSUPPORTED"
    with pytest.raises(AIError) as compatibility_error:
        harnesses.validate_pair("openai_compatible", "anthropic_native")
    assert compatibility_error.value.code == "AI_HARNESS_UNSUPPORTED"


async def test_configured_capability_is_not_inferred_from_provider_name() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        provider = OpenAICompatibleTransport(client)
        with pytest.raises(AIError) as error:
            await provider.generate(
                _request(tools=(_tool(),)),
                _config(tools=False),
                OpenAIChatHarness(),
            )
    assert error.value.code == "AI_CAPABILITY_UNSUPPORTED"
