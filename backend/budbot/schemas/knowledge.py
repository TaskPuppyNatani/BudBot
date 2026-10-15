"""Bounded administrative FAQ input and output, separate from customer lookup."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import ConfigDict, StringConstraints, model_validator

from budbot.schemas.common import DomainSchema

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Answer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class FAQCreate(DomainSchema):
    model_config = ConfigDict(extra="forbid")

    question: Question
    answer: Answer
    location_id: UUID | None = None
    enabled: bool = True
    is_public: bool = True


class FAQUpdate(DomainSchema):
    model_config = ConfigDict(extra="forbid")

    question: Question | None = None
    answer: Answer | None = None
    location_id: UUID | None = None
    enabled: bool | None = None
    is_public: bool | None = None

    @model_validator(mode="after")
    def require_valid_patch(self) -> "FAQUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one FAQ field must be supplied")
        for name in self.model_fields_set - {"location_id"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class FAQRead(DomainSchema):
    id: UUID
    business_id: UUID
    location_id: UUID | None
    question: str
    answer: str
    enabled: bool
    is_public: bool
    created_at: datetime
    updated_at: datetime
