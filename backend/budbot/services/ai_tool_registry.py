"""Explicit bridge from normalized AI calls to authorized M4 customer commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Type
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.commands.bootstrap import build_command_executor
from budbot.commands.executor import CommandExecutor
from budbot.commands.types import CommandExecutionContext, CommandScope
from budbot.core.exceptions import CommandError
from budbot.core.tenancy import TenantContext
from budbot.providers.ai.base import AIToolCall, AIToolDefinition
from budbot.providers.ai.errors import AIError


MAX_TOOL_RESULT_CHARS = 20_000


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _EmptyArguments(_Arguments):
    pass


class _QueryArguments(_Arguments):
    query: str = Field(min_length=1, max_length=240)

    @field_validator("query")
    @classmethod
    def require_nonblank_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class _ProductsArguments(_Arguments):
    category: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("category must not be blank")
        return normalized


@dataclass(frozen=True, slots=True)
class _ToolSpec:
    name: str
    command: str
    description: str
    arguments: Type[_Arguments]

    @property
    def definition(self) -> AIToolDefinition:
        schema = self.arguments.model_json_schema()
        return AIToolDefinition(
            name=self.name,
            description=self.description,
            parameters=schema,
        )


@dataclass(frozen=True, slots=True)
class AIToolExecutionResult:
    """Keep deterministic customer output separate from provider tool data."""

    command: str
    output: str

    def to_model_content(self) -> str:
        return json.dumps(
            {"command": self.command, "result": self.output},
            ensure_ascii=False,
            separators=(",", ":"),
        )


_SPECS = (
    _ToolSpec("list_locations", "locations", "List active business locations.", _EmptyArguments),
    _ToolSpec("get_hours", "hours", "Read configured weekly hours for the selected location.", _EmptyArguments),
    _ToolSpec("get_contact", "contact", "Read public contact information for the selected location.", _EmptyArguments),
    _ToolSpec("search_faq", "faq", "Search enabled public FAQs using the supplied terms.", _QueryArguments),
    _ToolSpec("list_products", "products", "List factual products offered at the selected location.", _ProductsArguments),
    _ToolSpec("search_products", "search", "Search factual catalog entries at the selected location.", _QueryArguments),
    _ToolSpec("list_categories", "categories", "List categories represented in the selected location's catalog.", _EmptyArguments),
    _ToolSpec("list_deals", "deals", "List active configured deals for the selected location.", _EmptyArguments),
)
_BY_NAME = {spec.name: spec for spec in _SPECS}


class AIToolRegistry:
    """Advertise only available tools and execute only these static mappings."""

    def __init__(self, executor: CommandExecutor | None = None) -> None:
        self.executor = executor or build_command_executor()

    async def available_tools(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        session_id: UUID,
    ) -> tuple[AIToolDefinition, ...]:
        context = self._context(session, tenant, session_id)
        metadata = await self.executor.metadata(context)
        available_commands = {
            item.name for item in metadata if item.available
        }
        return tuple(
            spec.definition for spec in _SPECS if spec.command in available_commands
        )

    async def execute(
        self,
        call: AIToolCall,
        *,
        available_names: frozenset[str],
        session: AsyncSession,
        tenant: TenantContext,
        session_id: UUID,
    ) -> AIToolExecutionResult:
        spec = _BY_NAME.get(call.name)
        if spec is None:
            raise AIError("AI_TOOL_CALL_INVALID")
        if call.name not in available_names:
            raise AIError("AI_TOOL_NOT_AVAILABLE")
        try:
            arguments = spec.arguments.model_validate(dict(call.arguments), strict=True)
        except ValidationError as exc:
            raise AIError("AI_TOOL_CALL_INVALID") from exc
        command = self._command(spec, arguments)
        try:
            result = await self.executor.execute(
                command, self._context(session, tenant, session_id)
            )
        except CommandError as exc:
            if exc.code in {"COMMAND_UNAVAILABLE", "COMMAND_PERMISSION_DENIED"}:
                raise AIError("AI_TOOL_NOT_AVAILABLE") from exc
            raise
        text = result.output
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "\n[Result truncated; ask a narrower question.]"
        return AIToolExecutionResult(command=spec.command, output=text)

    @staticmethod
    def _context(
        session: AsyncSession, tenant: TenantContext, session_id: UUID
    ) -> CommandExecutionContext:
        return CommandExecutionContext(
            session=session,
            tenant=tenant,
            scope=CommandScope.CUSTOMER,
            customer_session_id=session_id,
        )

    @staticmethod
    def _command(spec: _ToolSpec, arguments: BaseModel) -> str:
        values = arguments.model_dump(exclude_none=True)
        if spec.name == "search_faq":
            return f"/faq {values['query']}"
        if spec.name == "search_products":
            return f"/search {values['query']}"
        if spec.name == "list_products" and "category" in values:
            return f"/products {values['category']}"
        if values:
            raise AIError("AI_TOOL_CALL_INVALID")
        return f"/{spec.command}"
