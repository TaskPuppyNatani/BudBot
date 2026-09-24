"""Small, explicit adapters for OpenAI-style, Qwen-style, and Anthropic messages."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from budbot.providers.ai.base import (
    AIFinishReason,
    AIMessage,
    AIMessageRole,
    AIProviderConfig,
    AIRequest,
    AIResponse,
    AIToolCall,
    AIUsage,
    ModelHarness,
    thaw_json,
)
from budbot.providers.ai.errors import AIError


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise AIError("AI_PROVIDER_BAD_RESPONSE")
    return value


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise AIError("AI_PROVIDER_BAD_RESPONSE")
    return value


def _parse_json_object(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return _mapping(value)
    if not isinstance(value, str) or len(value) > 16_384:
        raise AIError("AI_PROVIDER_BAD_RESPONSE")
    try:
        parsed = json.loads(
            value,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise AIError("AI_PROVIDER_BAD_RESPONSE") from exc
    return _mapping(parsed)


def _usage(payload: object, config: AIProviderConfig) -> AIUsage | None:
    if payload is None or not config.capabilities.usage_reporting:
        return None
    values = _mapping(payload)
    input_tokens = values.get("prompt_tokens", values.get("input_tokens"))
    output_tokens = values.get("completion_tokens", values.get("output_tokens"))
    total_tokens = values.get("total_tokens")
    normalized: list[int | None] = []
    for value in (input_tokens, output_tokens, total_tokens):
        if value is None:
            normalized.append(None)
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        else:
            normalized.append(value)
    return AIUsage(*normalized)


def _finish_reason(value: object, *, has_tools: bool) -> AIFinishReason:
    if has_tools:
        return AIFinishReason.TOOL_CALLS
    if not isinstance(value, str):
        return AIFinishReason.UNKNOWN
    if value in {"stop", "end_turn", "completed"}:
        return AIFinishReason.STOP
    if value in {"length", "max_tokens"}:
        return AIFinishReason.LENGTH
    if value in {"content_filter", "refusal"}:
        return AIFinishReason.CONTENT_FILTER
    return AIFinishReason.UNKNOWN


class OpenAIChatHarness:
    """Translate normalized BudBot messages to the Chat Completions shape."""

    def __init__(self, key: str = "generic_openai", *, token_field: str = "max_tokens") -> None:
        self.key = key
        self.token_field = token_field

    def encode_request(
        self, request: AIRequest, config: AIProviderConfig
    ) -> Mapping[str, object]:
        messages: list[dict[str, object]] = []
        for message in request.messages:
            value: dict[str, object] = {
                "role": message.role.value,
                "content": message.content,
            }
            if message.name is not None:
                value["name"] = message.name
            if message.tool_call_id is not None:
                value["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                value["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                thaw_json(call.arguments),
                                ensure_ascii=False,
                                separators=(",", ":"),
                                allow_nan=False,
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(value)

        body: dict[str, object] = {"model": request.model, "messages": messages}
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": thaw_json(tool.parameters),
                    },
                }
                for tool in request.tools
            ]
            body["tool_choice"] = "auto"
        if request.generation.temperature is not None:
            body["temperature"] = request.generation.temperature
        output_limit = request.generation.max_output_tokens
        if output_limit is None and config.capabilities.max_output_tokens:
            output_limit = config.max_output_tokens
        if output_limit is not None:
            body[self.token_field] = output_limit
        return body

    def decode_response(
        self,
        payload: Mapping[str, object],
        request: AIRequest,
        config: AIProviderConfig,
    ) -> AIResponse:
        root = _mapping(payload)
        choices = _sequence(root.get("choices"))
        if not choices:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        choice = _mapping(choices[0])
        message = _mapping(choice.get("message"))
        if message.get("role", "assistant") != "assistant":
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        calls = self._tool_calls(message.get("tool_calls", ()))
        if calls and not config.capabilities.tool_calling:
            raise AIError("AI_CAPABILITY_UNSUPPORTED")
        reason = _finish_reason(choice.get("finish_reason"), has_tools=bool(calls))
        if reason is AIFinishReason.UNKNOWN and not calls:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        return AIResponse(
            content=content,
            finish_reason=reason,
            tool_calls=calls,
            provider=config.provider,
            model=config.model,
            harness=config.harness,
            usage=_usage(root.get("usage"), config),
            request_id=request.request_id,
        )

    @staticmethod
    def _tool_calls(raw_calls: object) -> tuple[AIToolCall, ...]:
        if raw_calls is None:
            return ()
        values = _sequence(raw_calls)
        if len(values) > 8:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        calls: list[AIToolCall] = []
        seen_ids: set[str] = set()
        for raw in values:
            item = _mapping(raw)
            function = _mapping(item.get("function"))
            call_id, name = item.get("id"), function.get("name")
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
            if call_id in seen_ids:
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
            seen_ids.add(call_id)
            arguments = _parse_json_object(function.get("arguments"))
            try:
                calls.append(AIToolCall(call_id, name, arguments))
            except ValueError as exc:
                raise AIError("AI_PROVIDER_BAD_RESPONSE") from exc
        return tuple(calls)


class OpenAICloudHarness(OpenAIChatHarness):
    """OpenAI's hosted chat API variant using its current output-token field."""

    def __init__(self) -> None:
        super().__init__("openai_chat", token_field="max_completion_tokens")


class QwenOpenAIHarness(OpenAIChatHarness):
    """Qwen serving behavior: discard hidden reasoning and strip think blocks."""

    key = "qwen_openai"
    _think_block = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)

    def __init__(self) -> None:
        super().__init__(self.key, token_field="max_tokens")

    def decode_response(
        self,
        payload: Mapping[str, object],
        request: AIRequest,
        config: AIProviderConfig,
    ) -> AIResponse:
        root = _mapping(payload)
        choices = _sequence(root.get("choices"))
        if not choices:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        choice = _mapping(choices[0])
        message = _mapping(choice.get("message"))
        raw_content = message.get("content")
        if raw_content is not None and not isinstance(raw_content, str):
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        if isinstance(raw_content, str):
            open_count = len(re.findall(r"<think>", raw_content, re.IGNORECASE))
            close_count = len(re.findall(r"</think>", raw_content, re.IGNORECASE))
            if open_count != close_count:
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
            content = self._think_block.sub("", raw_content).strip()
            if re.search(r"</?think>", content, re.IGNORECASE):
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
        else:
            content = None
        sanitized = dict(root)
        sanitized_choice = dict(choice)
        sanitized_message = dict(message)
        sanitized_message["content"] = content
        sanitized_choice["message"] = sanitized_message
        sanitized["choices"] = [sanitized_choice]
        # `reasoning_content` and sibling private reasoning fields are deliberately
        # never copied to normalized output or tool messages.
        return super().decode_response(sanitized, request, config)


class AnthropicNativeHarness:
    """Translate normalized messages to Anthropic's native Messages protocol."""

    key = "anthropic_native"

    def encode_request(
        self, request: AIRequest, config: AIProviderConfig
    ) -> Mapping[str, object]:
        system = "\n\n".join(
            message.content
            for message in request.messages
            if message.role is AIMessageRole.SYSTEM
        )
        messages: list[dict[str, object]] = []
        for message in request.messages:
            if message.role is AIMessageRole.SYSTEM:
                continue
            if message.role is AIMessageRole.TOOL:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
            elif message.tool_calls:
                content: list[dict[str, object]] = []
                if message.content:
                    content.append({"type": "text", "text": message.content})
                content.extend(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": thaw_json(call.arguments),
                    }
                    for call in message.tool_calls
                )
                messages.append({"role": "assistant", "content": content})
            else:
                role = "assistant" if message.role is AIMessageRole.ASSISTANT else "user"
                messages.append({"role": role, "content": message.content})

        body: dict[str, object] = {
            "model": request.model,
            "messages": messages,
        }
        output_limit = request.generation.max_output_tokens
        if output_limit is None and config.capabilities.max_output_tokens:
            output_limit = config.max_output_tokens
        if output_limit is not None:
            body["max_tokens"] = output_limit
        if system:
            body["system"] = system
        if request.tools:
            body["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": thaw_json(tool.parameters),
                }
                for tool in request.tools
            ]
            body["tool_choice"] = {"type": "auto"}
        if request.generation.temperature is not None:
            body["temperature"] = request.generation.temperature
        return body

    def decode_response(
        self,
        payload: Mapping[str, object],
        request: AIRequest,
        config: AIProviderConfig,
    ) -> AIResponse:
        root = _mapping(payload)
        blocks = _sequence(root.get("content"))
        text_parts: list[str] = []
        calls: list[AIToolCall] = []
        seen_ids: set[str] = set()
        for raw in blocks:
            block = _mapping(raw)
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise AIError("AI_PROVIDER_BAD_RESPONSE")
                text_parts.append(text)
            elif block_type == "tool_use":
                call_id, name = block.get("id"), block.get("name")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    raise AIError("AI_PROVIDER_BAD_RESPONSE")
                if call_id in seen_ids:
                    raise AIError("AI_PROVIDER_BAD_RESPONSE")
                seen_ids.add(call_id)
                try:
                    calls.append(AIToolCall(call_id, name, _mapping(block.get("input"))))
                except ValueError as exc:
                    raise AIError("AI_PROVIDER_BAD_RESPONSE") from exc
            else:
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
        if calls and not config.capabilities.tool_calling:
            raise AIError("AI_CAPABILITY_UNSUPPORTED")
        finish = _finish_reason(root.get("stop_reason"), has_tools=bool(calls))
        if finish is AIFinishReason.UNKNOWN:
            raise AIError("AI_PROVIDER_BAD_RESPONSE")
        usage = _usage(root.get("usage"), config)
        return AIResponse(
            content="\n".join(text_parts) if text_parts else None,
            finish_reason=finish,
            tool_calls=tuple(calls),
            provider=config.provider,
            model=config.model,
            harness=config.harness,
            usage=usage,
            request_id=request.request_id,
        )


def normalize_openai_response(
    payload: Mapping[str, object], request: AIRequest, config: AIProviderConfig
) -> AIResponse:
    """Small helper for provider contract tests and compatible adapters."""

    return OpenAIChatHarness().decode_response(payload, request, config)
