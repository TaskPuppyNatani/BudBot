"""Honest M5 no-op until conversational history exists."""

from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand


async def clear(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    return command_result(
        parsed,
        "No conversational history is stored yet, so there is nothing to clear. Your selected location and compliance/session status are unchanged.",
    )
