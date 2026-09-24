"""Minimal public chat request; provider and harness remain server-owned."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    message: str = Field(min_length=1, max_length=4_000)

    @field_validator("message")
    @classmethod
    def require_nonblank_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
