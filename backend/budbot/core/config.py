"""Typed runtime configuration loaded from environment variables."""

from functools import lru_cache
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-level settings.

    Business and tenant configuration belongs in the database in later
    milestones; this class is intentionally limited to application runtime
    configuration.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="BUDBOT_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(min_length=1)
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    customer_session_ttl_seconds: int = Field(
        default=86_400, ge=60, le=2_592_000
    )
    ai_enabled: bool = False
    ai_provider: str = "openai_compatible"
    ai_base_url: str | None = None
    ai_model: str | None = Field(default=None, min_length=1, max_length=200)
    ai_harness: str = "generic_openai"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    ai_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    ai_max_output_tokens: int = Field(default=800, ge=1, le=16_384)
    ai_temperature: float | None = Field(default=None, ge=0, le=2)
    ai_capability_text_generation: bool = True
    ai_capability_tool_calling: bool = False
    ai_capability_usage_reporting: bool = False
    ai_capability_temperature: bool = False
    ai_capability_max_output_tokens: bool = True
    ai_capability_structured_output: bool = False
    ai_capability_system_role: bool = True
    ai_capability_reasoning_control: bool = False

    @field_validator("database_url")
    @classmethod
    def require_async_postgresql_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "BUDBOT_DATABASE_URL must use PostgreSQL with the asyncpg driver "
                "(postgresql+asyncpg://...)"
            )
        return value

    @field_validator("ai_model")
    @classmethod
    def normalize_ai_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("BUDBOT_AI_MODEL must be non-empty and at most 200 characters")
        return normalized

    @field_validator("ai_provider", "ai_harness")
    @classmethod
    def require_registry_key_shape(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", normalized):
            raise ValueError("AI provider and harness values must be registry keys")
        return normalized

    @field_validator("ai_base_url")
    @classmethod
    def validate_ai_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "BUDBOT_AI_BASE_URL must be an http(s) base URL without credentials, query, or fragment"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return the validated process settings."""

    return Settings()
