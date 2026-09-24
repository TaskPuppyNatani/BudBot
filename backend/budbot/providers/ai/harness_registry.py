"""Explicit model/serving-harness registry."""

from budbot.providers.ai.base import ModelHarness
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.harnesses import (
    AnthropicNativeHarness,
    OpenAIChatHarness,
    OpenAICloudHarness,
    QwenOpenAIHarness,
)


class AIHarnessRegistry:
    def __init__(self) -> None:
        self._harnesses: dict[str, ModelHarness] = {}

    def register(self, key: str, harness: ModelHarness) -> None:
        if not key or key in self._harnesses or harness.key != key:
            raise ValueError("AI harness keys must be unique and match the adapter")
        self._harnesses[key] = harness

    def resolve(self, key: str) -> ModelHarness:
        try:
            return self._harnesses[key]
        except KeyError as exc:
            raise AIError("AI_HARNESS_UNSUPPORTED") from exc

    def validate_pair(self, provider: str, harness: str) -> None:
        allowed = {
            "openai_compatible": {"generic_openai", "qwen_openai"},
            "openai": {"openai_chat"},
            "anthropic": {"anthropic_native"},
            "mock": {"generic_openai", "qwen_openai", "openai_chat", "anthropic_native"},
        }
        if harness not in allowed.get(provider, set()):
            if provider not in allowed:
                raise AIError("AI_PROVIDER_UNKNOWN")
            raise AIError("AI_HARNESS_UNSUPPORTED")
        self.resolve(harness)


def build_ai_harness_registry() -> AIHarnessRegistry:
    registry = AIHarnessRegistry()
    for harness in (
        OpenAIChatHarness(),
        QwenOpenAIHarness(),
        OpenAICloudHarness(),
        AnthropicNativeHarness(),
    ):
        registry.register(harness.key, harness)
    return registry
