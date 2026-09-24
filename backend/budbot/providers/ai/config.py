"""Resolve trusted process settings into one provider/model/harness configuration."""

from budbot.core.config import Settings
from budbot.providers.ai.base import AICapabilities, AIProviderConfig
from budbot.providers.ai.errors import AIError


def provider_config_from_settings(settings: Settings) -> AIProviderConfig:
    if not settings.ai_enabled:
        raise AIError("AI_DISABLED")
    if not settings.ai_model:
        raise AIError("AI_CONFIGURATION_INVALID")
    provider = settings.ai_provider
    if provider == "openai_compatible" and not settings.ai_base_url:
        raise AIError("AI_CONFIGURATION_INVALID")
    if provider in {"openai", "anthropic"} and settings.ai_api_key is None:
        raise AIError("AI_CONFIGURATION_INVALID")
    capabilities = AICapabilities(
        text_generation=settings.ai_capability_text_generation,
        tool_calling=settings.ai_capability_tool_calling,
        usage_reporting=settings.ai_capability_usage_reporting,
        temperature=settings.ai_capability_temperature,
        max_output_tokens=settings.ai_capability_max_output_tokens,
        structured_output=settings.ai_capability_structured_output,
        system_role=settings.ai_capability_system_role,
        reasoning_control=settings.ai_capability_reasoning_control,
    )
    return AIProviderConfig(
        provider=provider,
        model=settings.ai_model,
        harness=settings.ai_harness,
        base_url=settings.ai_base_url,
        api_key=(
            settings.ai_api_key.get_secret_value()
            if settings.ai_api_key is not None
            else None
        ),
        timeout_seconds=settings.ai_timeout_seconds,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        max_output_tokens=settings.ai_max_output_tokens,
        capabilities=capabilities,
    )
