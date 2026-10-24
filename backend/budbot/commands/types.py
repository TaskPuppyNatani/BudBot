"""Explicit command definitions and execution values."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.registry import ComplianceCapability
from budbot.core.exceptions import CommandError
from budbot.core.tenancy import TenantContext
from budbot.models.session import CustomerSession

if TYPE_CHECKING:
    from budbot.core.config import Settings
    from budbot.providers.ai.registry import AIProviderRegistry
    from budbot.providers.ai.harness_registry import AIHarnessRegistry


class CommandScope(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class CustomCommandAction(StrEnum):
    """Future safe declarative actions; none execute in M4."""

    KNOWLEDGE_RESPONSE = "knowledge_response"
    EXTERNAL_LINK = "external_link"
    LOCATION_INFO = "location_info"


@dataclass(frozen=True, slots=True)
class CommandArguments:
    help_hint: str = ""
    minimum: int = 0
    maximum: int | None = 0

    def validate(self, values: tuple[str, ...]) -> None:
        if len(values) < self.minimum or (
            self.maximum is not None and len(values) > self.maximum
        ):
            hint = f" Usage: {self.help_hint}" if self.help_hint else ""
            raise CommandError(
                "COMMAND_ARGUMENT_ERROR",
                f"the command arguments are invalid.{hint}",
            )


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    canonical_name: str
    requested_name: str
    raw_arguments: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionContext:
    """Trusted permissions supplied by the authenticated administrative transport."""

    authenticated_admin: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class AdminCommandRuntime:
    """Server-resolved administrative identity/resources; never accepted as input."""

    user_id: UUID
    location_id: UUID | None
    settings: Settings
    providers: AIProviderRegistry
    harnesses: AIHarnessRegistry


@dataclass(frozen=True, slots=True)
class CommandExecutionContext:
    session: AsyncSession
    tenant: TenantContext
    scope: CommandScope
    customer_session_id: UUID | None = None
    customer_session: CustomerSession | None = None
    permission_context: PermissionContext = field(default_factory=PermissionContext)
    features: frozenset[str] | None = None
    admin_runtime: AdminCommandRuntime | None = None


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    name: str
    description: str
    aliases: tuple[str, ...]
    scope: CommandScope
    argument_hint: str
    available: bool


@dataclass(frozen=True, slots=True)
class CommandResult:
    canonical_name: str
    requested_name: str
    output: str
    commands: tuple[CommandMetadata, ...] = ()
    selected_location_id: UUID | None = None
    preview_url: str | None = None


CommandHandler = Callable[
    [CommandExecutionContext, ParsedCommand], Awaitable[CommandResult]
]


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    name: str
    description: str
    scope: CommandScope
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    arguments: CommandArguments = field(default_factory=CommandArguments)
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    required_features: frozenset[str] = field(default_factory=frozenset)
    compliance_capability: ComplianceCapability | str | None = None
    visible: bool = True
    autocomplete: bool = True
    protected: bool = True


@dataclass(frozen=True, slots=True)
class CustomCommandDefinition:
    """Non-executable declarative shape reserved for later persistence/runtime work."""

    name: str
    description: str
    action: CustomCommandAction
    parameters: Mapping[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
