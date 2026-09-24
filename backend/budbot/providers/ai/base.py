"""Normalized AI values and the provider/harness contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, TypeAlias
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from budbot.providers.ai.errors import AIError


JSONValue: TypeAlias = (
    str | int | float | bool | None | tuple["JSONValue", ...] | Mapping[str, "JSONValue"]
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _freeze_json(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("value is not JSON-compatible")


def thaw_json(value: JSONValue) -> object:
    """Return ordinary JSON containers for a transport encoder."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class AIMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AIFinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AIToolCall:
    id: str
    name: str
    arguments: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        if not self.id or len(self.id) > 128 or not _IDENTIFIER.fullmatch(self.id):
            raise ValueError("tool call ID is invalid")
        if not _TOOL_NAME.fullmatch(self.name):
            raise ValueError("tool name is invalid")
        frozen = _freeze_json(self.arguments)
        if not isinstance(frozen, Mapping):
            raise ValueError("tool arguments must be a JSON object")
        object.__setattr__(self, "arguments", frozen)


@dataclass(frozen=True, slots=True)
class AIMessage:
    role: AIMessageRole
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[AIToolCall, ...] = ()

    def __post_init__(self) -> None:
        try:
            role = AIMessageRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ValueError("message role is unsupported") from exc
        object.__setattr__(self, "role", role)
        if not isinstance(self.content, str) or len(self.content) > 40_000:
            raise ValueError("message content is invalid or too large")
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if role is AIMessageRole.TOOL:
            if not self.tool_call_id or not _IDENTIFIER.fullmatch(self.tool_call_id):
                raise ValueError("tool messages require a valid tool call ID")
            if self.tool_calls:
                raise ValueError("tool messages cannot contain tool calls")
        elif self.tool_call_id is not None:
            raise ValueError("only tool messages may contain a tool call ID")
        if self.tool_calls and role is not AIMessageRole.ASSISTANT:
            raise ValueError("only assistant messages may contain tool calls")
        if self.name is not None and not _IDENTIFIER.fullmatch(self.name):
            raise ValueError("message name is invalid")


@dataclass(frozen=True, slots=True)
class AIToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        if not _TOOL_NAME.fullmatch(self.name):
            raise ValueError("tool name is invalid")
        if not self.description or len(self.description) > 1000:
            raise ValueError("tool description is invalid")
        frozen = _freeze_json(self.parameters)
        if not isinstance(frozen, Mapping):
            raise ValueError("tool parameters must be a JSON object")
        object.__setattr__(self, "parameters", frozen)


@dataclass(frozen=True, slots=True)
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (self.input_tokens, self.output_tokens, self.total_tokens):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError("usage token counts must be nonnegative integers")


@dataclass(frozen=True, slots=True)
class AICapabilities:
    """Operator-declared capabilities for one provider/model/harness tuple."""

    text_generation: bool = True
    tool_calling: bool = False
    usage_reporting: bool = False
    temperature: bool = False
    max_output_tokens: bool = True
    structured_output: bool = False
    system_role: bool = True
    reasoning_control: bool = False


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None and (
            not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool) or self.max_output_tokens < 1
        ):
            raise ValueError("max output tokens must be positive")


@dataclass(frozen=True, slots=True)
class AIRequest:
    messages: tuple[AIMessage, ...]
    model: str
    harness: str
    tools: tuple[AIToolDefinition, ...] = ()
    generation: GenerationOptions = GenerationOptions()
    request_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if not self.model or len(self.model) > 200 or not self.model.strip():
            raise ValueError("model identifier is invalid")
        if not _IDENTIFIER.fullmatch(self.harness):
            raise ValueError("harness identifier is invalid")
        if len(self.messages) > 32:
            raise ValueError("AI requests may contain at most 32 messages")
        if len(self.tools) > 32:
            raise ValueError("AI requests may contain at most 32 tools")


@dataclass(frozen=True, slots=True)
class AIResponse:
    content: str | None
    finish_reason: AIFinishReason
    tool_calls: tuple[AIToolCall, ...]
    provider: str
    model: str
    harness: str
    usage: AIUsage | None = None
    request_id: UUID | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "finish_reason", AIFinishReason(self.finish_reason))
        except (TypeError, ValueError) as exc:
            raise ValueError("finish reason is invalid") from exc
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if self.content is not None and (
            not isinstance(self.content, str) or len(self.content) > 40_000
        ):
            raise ValueError("AI response text is invalid or too large")
        if self.finish_reason is AIFinishReason.TOOL_CALLS and not self.tool_calls:
            raise ValueError("tool-call finish reason requires tool calls")
        if self.tool_calls and self.finish_reason is not AIFinishReason.TOOL_CALLS:
            raise ValueError("responses with tool calls must use the tool-call finish reason")
        if not self.provider or not self.model or not self.harness:
            raise ValueError("AI response identity metadata is required")


@dataclass(frozen=True, slots=True)
class AIProviderConfig:
    provider: str
    model: str
    harness: str
    base_url: str | None
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    max_output_tokens: int = 800
    capabilities: AICapabilities = AICapabilities()

    def __post_init__(self) -> None:
        if (
            not self.model.strip()
            or len(self.model) > 200
            or not _IDENTIFIER.fullmatch(self.provider)
            or not _IDENTIFIER.fullmatch(self.harness)
        ):
            raise ValueError("model identifier is invalid")
        if self.timeout_seconds <= 0 or self.connect_timeout_seconds <= 0:
            raise ValueError("AI timeouts must be positive")
        if self.max_output_tokens < 1:
            raise ValueError("maximum output tokens must be positive")
        if self.api_key is not None and (
            len(self.api_key) > 10_000 or "\r" in self.api_key or "\n" in self.api_key
        ):
            raise ValueError("AI credential is invalid")
        if self.base_url is not None:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("AI base URL is invalid")


class ModelHarness(Protocol):
    """Translate normalized messages to/from one model/serving behavior."""

    key: str

    def encode_request(
        self, request: AIRequest, config: AIProviderConfig
    ) -> Mapping[str, object]: ...

    def decode_response(
        self,
        payload: Mapping[str, object],
        request: AIRequest,
        config: AIProviderConfig,
    ) -> AIResponse: ...


class ProviderTransport(Protocol):
    """Deliver normalized requests using one provider wire protocol."""

    async def generate(
        self,
        request: AIRequest,
        config: AIProviderConfig,
        harness: ModelHarness,
    ) -> AIResponse: ...


def require_tool_capability(request: AIRequest, config: AIProviderConfig) -> None:
    if request.tools and not config.capabilities.tool_calling:
        raise AIError("AI_CAPABILITY_UNSUPPORTED")
    if any(message.role is AIMessageRole.SYSTEM for message in request.messages):
        if not config.capabilities.system_role:
            raise AIError("AI_CAPABILITY_UNSUPPORTED")
    if request.generation.temperature is not None and not config.capabilities.temperature:
        raise AIError("AI_CAPABILITY_UNSUPPORTED")
    if (
        request.generation.max_output_tokens is not None
        and not config.capabilities.max_output_tokens
    ):
        raise AIError("AI_CAPABILITY_UNSUPPORTED")
    if (
        request.generation.reasoning_effort is not None
        and not config.capabilities.reasoning_control
    ):
        raise AIError("AI_CAPABILITY_UNSUPPORTED")
