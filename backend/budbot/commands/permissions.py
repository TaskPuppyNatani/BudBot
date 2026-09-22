"""Replaceable permission evaluation for command execution."""

from budbot.commands.types import CommandDefinition, CommandExecutionContext, CommandScope
from budbot.core.exceptions import CommandError


class CommandPermissionEvaluator:
    def authorize(
        self,
        definition: CommandDefinition,
        context: CommandExecutionContext,
    ) -> None:
        permissions = context.permission_context
        if definition.scope is CommandScope.ADMIN and not permissions.authenticated_admin:
            raise CommandError(
                "COMMAND_PERMISSION_DENIED",
                "authenticated administrative context is required",
                status_code=403,
            )
        if not definition.required_permissions <= permissions.permissions:
            raise CommandError(
                "COMMAND_PERMISSION_DENIED",
                "the command requires permissions that are not present",
                status_code=403,
            )
