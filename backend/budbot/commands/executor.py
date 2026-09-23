"""Authoritative command execution, availability, and help pipeline."""

from __future__ import annotations

from dataclasses import replace

from budbot.commands.parser import parse_command
from budbot.commands.permissions import CommandPermissionEvaluator
from budbot.commands.registry import CommandRegistry
from budbot.commands.types import (
    CommandDefinition,
    CommandExecutionContext,
    CommandMetadata,
    CommandResult,
    CommandScope,
    ParsedCommand,
)
from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.engine import ComplianceEngine
from budbot.core.exceptions import CommandError, ComplianceError
from budbot.services.assistant_service import AssistantService
from budbot.services.session_service import SessionService
from budbot.services.business_service import BusinessService


_HIDDEN_COMPLIANCE_DENIALS = {
    "AGE_VERIFICATION_DENIED",
    "AGE_VERIFICATION_REQUIRED",
    "CAPABILITY_PROHIBITED",
}


class CommandExecutor:
    def __init__(
        self,
        registry: CommandRegistry,
        *,
        permission_evaluator: CommandPermissionEvaluator | None = None,
    ) -> None:
        self.registry = registry
        self.permission_evaluator = permission_evaluator or CommandPermissionEvaluator()

    async def execute(
        self, value: str, context: CommandExecutionContext
    ) -> CommandResult:
        parsed = parse_command(value, self.registry, context.scope)
        if parsed is None:
            raise CommandError(
                "COMMAND_INVALID", "command execution requires slash-command input"
            )
        definition = self.registry.resolve(parsed.canonical_name, context.scope)
        prepared = await self._prepare_context(context)
        await self._authorize(definition, prepared)
        definition.arguments.validate(parsed.arguments)
        return await definition.handler(prepared, parsed)

    async def metadata(
        self,
        context: CommandExecutionContext,
        *,
        include_unavailable: bool = False,
    ) -> tuple[CommandMetadata, ...]:
        prepared = await self._prepare_context(context)
        return await self._metadata_for_prepared(
            prepared,
            include_unavailable=include_unavailable,
            autocomplete_only=True,
        )

    async def handle_help(
        self,
        context: CommandExecutionContext,
        parsed: ParsedCommand,
    ) -> CommandResult:
        commands = await self._metadata_for_prepared(
            context,
            include_unavailable=False,
            autocomplete_only=False,
        )
        if context.scope is CommandScope.CUSTOMER:
            assistant_name = await self._assistant_display_name(context)
            heading = f"{assistant_name} commands:"
        else:
            heading = "Available admin commands:"
        lines = [heading]
        for command in commands:
            alias_text = (
                f" (aliases: {', '.join('/' + alias for alias in command.aliases)})"
                if command.aliases
                else ""
            )
            lines.append(f"/{command.name} — {command.description}{alias_text}")
        return CommandResult(
            canonical_name=parsed.canonical_name,
            requested_name=parsed.requested_name,
            output="\n".join(lines),
            commands=commands,
        )

    async def _prepare_context(
        self, context: CommandExecutionContext
    ) -> CommandExecutionContext:
        if context.scope is not CommandScope.CUSTOMER:
            return replace(context, features=context.features or frozenset())
        session_id = context.customer_session_id
        if context.customer_session is not None:
            context.tenant.require_business(context.customer_session.business_id)
            session_id = context.customer_session.id
        if session_id is None:
            raise CommandError(
                "COMMAND_INVALID", "a customer session is required for this command"
            )
        customer_session = await SessionService(
            context.session, context.tenant
        ).get(session_id)
        if customer_session.age_gate_status == AgeGateStatus.EXPIRED:
            raise ComplianceError(
                "SESSION_EXPIRED",
                "the customer session has expired; create a new session",
                status_code=410,
            )
        features = context.features
        if features is None:
            business = await BusinessService(context.session).get(
                context.tenant, context.tenant.business_id
            )
            feature_names = (
                "directions_enabled", "faq_enabled", "payments_info_enabled",
                "policies_info_enabled",
            )
            features = frozenset(name for name in feature_names if getattr(business, name))
        return replace(
            context,
            customer_session_id=session_id,
            customer_session=customer_session,
            features=features,
        )

    async def _authorize(
        self,
        definition: CommandDefinition,
        context: CommandExecutionContext,
    ) -> None:
        if definition.scope is not context.scope:
            raise CommandError(
                "COMMAND_SCOPE_DENIED",
                "the command is not available in this command scope",
                status_code=403,
            )
        self.permission_evaluator.authorize(definition, context)
        if not definition.required_features <= context.features:
            raise CommandError(
                "COMMAND_UNAVAILABLE",
                "the command is unavailable in the current feature context",
                status_code=403,
            )
        if definition.compliance_capability is not None:
            if context.customer_session is None:
                raise CommandError(
                    "COMMAND_UNAVAILABLE",
                    "the command requires a customer compliance context",
                    status_code=403,
                )
            await ComplianceEngine(context.session, context.tenant).authorize(
                context.customer_session,
                definition.compliance_capability,
            )

    async def _metadata_for_prepared(
        self,
        context: CommandExecutionContext,
        *,
        include_unavailable: bool,
        autocomplete_only: bool,
    ) -> tuple[CommandMetadata, ...]:
        metadata: list[CommandMetadata] = []
        for definition in self.registry.definitions(context.scope):
            if not definition.visible or (
                autocomplete_only and not definition.autocomplete
            ):
                continue
            available = await self._is_available(definition, context)
            if available or include_unavailable:
                metadata.append(
                    CommandMetadata(
                        name=definition.name,
                        description=definition.description,
                        aliases=definition.aliases,
                        scope=definition.scope,
                        argument_hint=definition.arguments.help_hint,
                        available=available,
                    )
                )
        return tuple(metadata)

    async def _is_available(
        self,
        definition: CommandDefinition,
        context: CommandExecutionContext,
    ) -> bool:
        try:
            await self._authorize(definition, context)
        except CommandError as exc:
            if exc.code in {"COMMAND_PERMISSION_DENIED", "COMMAND_UNAVAILABLE"}:
                return False
            raise
        except ComplianceError as exc:
            if exc.code in _HIDDEN_COMPLIANCE_DENIALS:
                return False
            raise
        return True

    async def _assistant_display_name(
        self, context: CommandExecutionContext
    ) -> str:
        service = AssistantService(context.session, context.tenant)
        customer_session = context.customer_session
        if customer_session and customer_session.selected_location_id is not None:
            effective = await service.resolve(
                context.tenant.business_id,
                customer_session.selected_location_id,
            )
            return effective.display_name
        assistant = await service.get(context.tenant.business_id)
        return assistant.display_name
