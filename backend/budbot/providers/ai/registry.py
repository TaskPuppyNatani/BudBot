"""Explicit provider-transport registry and default adapter assembly."""

from budbot.providers.ai.base import ProviderTransport
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.mock import MockAIProvider
from budbot.providers.ai.openai import OpenAITransport
from budbot.providers.ai.openai_compatible import OpenAICompatibleTransport
from budbot.providers.ai.anthropic import AnthropicTransport
import httpx


class AIProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderTransport] = {}

    def register(self, key: str, provider: ProviderTransport) -> None:
        if not key or key in self._providers:
            raise ValueError("AI provider keys must be unique")
        self._providers[key] = provider

    def resolve(self, key: str) -> ProviderTransport:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise AIError("AI_PROVIDER_UNKNOWN") from exc


def build_ai_provider_registry(
    client: httpx.AsyncClient,
    *,
    mock_provider: MockAIProvider | None = None,
) -> AIProviderRegistry:
    """Build known runtime transports; inject mock only in deterministic tests."""

    registry = AIProviderRegistry()
    registry.register("openai_compatible", OpenAICompatibleTransport(client))
    registry.register("openai", OpenAITransport(client))
    registry.register("anthropic", AnthropicTransport(client))
    if mock_provider is not None:
        registry.register("mock", mock_provider)
    return registry
