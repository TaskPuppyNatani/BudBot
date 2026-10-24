"""Explicit M4 framework command bootstrap."""

from budbot.commands.executor import CommandExecutor
from budbot.commands.registry import CommandRegistry
from budbot.commands.types import CommandDefinition, CommandScope
from budbot.commands.customer.registration import register_customer_commands
from budbot.commands.admin.registration import register_admin_commands


ADMIN_HELP_PERMISSION = "commands:read"


def build_command_executor() -> CommandExecutor:
    registry = CommandRegistry()
    executor = CommandExecutor(registry)
    registry.register(
        CommandDefinition(
            name="help",
            description="Show commands available in the current customer context.",
            scope=CommandScope.CUSTOMER,
            handler=executor.handle_help,
        )
    )
    registry.register(
        CommandDefinition(
            name="help",
            description="Show commands available in the current admin context.",
            scope=CommandScope.ADMIN,
            handler=executor.handle_help,
            required_permissions=frozenset({ADMIN_HELP_PERMISSION}),
        )
    )
    register_customer_commands(registry, executor)
    register_admin_commands(registry)
    return executor
