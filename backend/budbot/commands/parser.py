"""Small deterministic slash-command parser."""

from budbot.commands.registry import CommandRegistry
from budbot.commands.types import CommandScope, ParsedCommand
from budbot.core.exceptions import CommandError


def parse_command(
    value: str,
    registry: CommandRegistry,
    scope: CommandScope,
) -> ParsedCommand | None:
    stripped = value.strip()
    if not stripped.startswith("/"):
        return None
    body = stripped[1:]
    if not body or body[0].isspace():
        raise CommandError("COMMAND_INVALID", "a command name is required")

    parts = body.split(maxsplit=1)
    requested_name = parts[0]
    if "/" in requested_name:
        raise CommandError("COMMAND_INVALID", "the command name is malformed")
    definition = registry.resolve(requested_name, scope)
    raw_arguments = parts[1].strip() if len(parts) == 2 else ""
    arguments = tuple(raw_arguments.split()) if raw_arguments else ()
    return ParsedCommand(
        canonical_name=definition.name,
        requested_name=requested_name.lower(),
        raw_arguments=raw_arguments,
        arguments=arguments,
    )
