"""Typed slash-command framework."""

from budbot.commands.bootstrap import build_command_executor
from budbot.commands.executor import CommandExecutor
from budbot.commands.registry import CommandRegistry
from budbot.commands.types import (
    CommandDefinition,
    CommandExecutionContext,
    CommandResult,
    CommandScope,
)

__all__ = [
    "CommandDefinition",
    "CommandExecutionContext",
    "CommandExecutor",
    "CommandRegistry",
    "CommandResult",
    "CommandScope",
    "build_command_executor",
]
