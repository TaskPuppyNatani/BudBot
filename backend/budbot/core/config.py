"""Typed runtime configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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

    @field_validator("database_url")
    @classmethod
    def require_async_postgresql_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "BUDBOT_DATABASE_URL must use PostgreSQL with the asyncpg driver "
                "(postgresql+asyncpg://...)"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the validated process settings."""

    return Settings()
