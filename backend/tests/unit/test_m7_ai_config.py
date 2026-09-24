"""Trusted operator AI configuration and capability validation tests."""

import pytest
from pydantic import ValidationError

from budbot.core.config import Settings
from budbot.providers.ai.base import AIProviderConfig
from budbot.providers.ai.config import provider_config_from_settings
from budbot.providers.ai.errors import AIError


def _settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+asyncpg://budbot:test@localhost:5432/budbot_test",
        **values,
    )


def test_ai_is_disabled_by_default_without_blocking_application_settings() -> None:
    settings = _settings()
    assert settings.ai_enabled is False
    with pytest.raises(AIError) as error:
        provider_config_from_settings(settings)
    assert error.value.code == "AI_DISABLED"


def test_operator_config_selects_model_endpoint_harness_and_capabilities_explicitly() -> None:
    settings = _settings(
        ai_enabled=True,
        ai_provider="openai_compatible",
        ai_base_url="http://127.0.0.1:1234/v1",
        ai_model="  operator-model  ",
        ai_harness="qwen_openai",
        ai_capability_tool_calling=True,
        ai_capability_usage_reporting=True,
    )
    config = provider_config_from_settings(settings)
    assert config.model == "operator-model"
    assert config.base_url == "http://127.0.0.1:1234/v1"
    assert config.harness == "qwen_openai"
    assert config.capabilities.tool_calling is True
    assert config.capabilities.usage_reporting is True


def test_ai_configuration_fails_safely_for_missing_model_endpoint_or_cloud_secret() -> None:
    with pytest.raises(AIError) as missing_model:
        provider_config_from_settings(_settings(ai_enabled=True))
    assert missing_model.value.code == "AI_CONFIGURATION_INVALID"

    with pytest.raises(AIError) as missing_endpoint:
        provider_config_from_settings(_settings(ai_enabled=True, ai_model="configured-model"))
    assert missing_endpoint.value.code == "AI_CONFIGURATION_INVALID"

    with pytest.raises(AIError) as missing_secret:
        provider_config_from_settings(
            _settings(ai_enabled=True, ai_provider="openai", ai_model="configured-model")
        )
    assert missing_secret.value.code == "AI_CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "http://user:password@localhost/v1",
        "http://localhost/v1?secret=token",
        "http://localhost/v1#fragment",
    ],
)
def test_base_url_rejects_credentials_non_http_schemes_and_query_data(url: str) -> None:
    with pytest.raises(ValidationError):
        _settings(ai_base_url=url)


def test_model_identifier_is_trimmed_and_bounded() -> None:
    assert _settings(ai_model="  local-name ").ai_model == "local-name"
    with pytest.raises(ValidationError):
        _settings(ai_model=" ")
    with pytest.raises(ValidationError):
        _settings(ai_model="m" * 201)


def test_secret_is_hidden_from_runtime_config_repr() -> None:
    config = AIProviderConfig(
        provider="openai",
        model="configured-model",
        harness="openai_chat",
        base_url=None,
        api_key="do-not-print-this",
    )
    assert "do-not-print-this" not in repr(config)
