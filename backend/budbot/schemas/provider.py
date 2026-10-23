"""Safe provider metadata and write-only credential input."""
from typing import Literal
from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator
from budbot.schemas.common import DomainSchema
from budbot.core.config import Settings

class ProviderUpdate(DomainSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    provider: Literal["openrouter", "openai_compatible", "openai", "anthropic"]
    model: str = Field(min_length=1, max_length=200)
    enabled: bool = False
    base_url: str | None = Field(default=None, max_length=2048)
    tool_calling: bool = False

    @field_validator("model")
    @classmethod
    def model_name(cls, value):
        if not value.strip():
            raise ValueError("Model is required.")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        if value and any(ord(c) < 32 for c in value):
            raise ValueError("Endpoint must not contain control characters.")
        return Settings.validate_ai_base_url(value)

    @model_validator(mode="after")
    def provider_fields(self):
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("An endpoint reachable from the backend is required.")
        if self.provider != "openai_compatible" and self.base_url is not None:
            raise ValueError("Custom endpoints are only allowed for OpenAI-compatible providers.")
        return self

class CredentialUpdate(DomainSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    credential: SecretStr = Field(min_length=1, max_length=10000, repr=False, exclude=True)

    @field_validator("credential")
    @classmethod
    def header_safe(cls, value):
        raw = value.get_secret_value()
        if not raw.strip() or any(ord(c) < 32 or ord(c) > 126 for c in raw):
            raise ValueError("Credential must be a non-empty printable API key.")
        return value

class ProviderRead(DomainSchema):
    configured: bool
    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    tool_calling: bool = False
    credential_configured: bool = False
