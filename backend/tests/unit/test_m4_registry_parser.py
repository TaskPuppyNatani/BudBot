"""M4 deterministic registry and parser behavior."""

import pytest

from budbot.commands.parser import parse_command
from budbot.commands.registry import CommandRegistrationError, CommandRegistry
from budbot.commands.types import (
    CommandDefinition,
    CommandExecutionContext,
    CommandResult,
    CommandScope,
    CustomCommandAction,
    CustomCommandDefinition,
    ParsedCommand,
)
from budbot.core.exceptions import CommandError


async def _handler(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    return CommandResult(parsed.canonical_name, parsed.requested_name, "ok")


def _definition(
    name: str,
    *,
    scope: CommandScope = CommandScope.CUSTOMER,
    aliases: tuple[str, ...] = (),
) -> CommandDefinition:
    return CommandDefinition(
        name=name,
        description=f"{name} description",
        scope=scope,
        aliases=aliases,
        handler=_handler,
    )


def test_registry_rejects_collisions_and_protected_custom_names() -> None:
    registry = CommandRegistry()
    registry.register(_definition("find", aliases=("lookup",)))

    assert registry.resolve("FIND", CommandScope.CUSTOMER).name == "find"
    assert registry.resolve("lookup", CommandScope.CUSTOMER).name == "find"
    with pytest.raises(CommandRegistrationError, match="already registered"):
        registry.register(_definition("find"))
    with pytest.raises(CommandRegistrationError, match="already registered"):
        registry.register(_definition("lookup"))
    with pytest.raises(CommandRegistrationError, match="already registered"):
        registry.register(_definition("other", aliases=("find",)))
    with pytest.raises(CommandRegistrationError, match="protected built-in"):
        registry.validate_custom_definition(
            CustomCommandDefinition(
                name="products",
                description="unsafe collision",
                action=CustomCommandAction.KNOWLEDGE_RESPONSE,
            )
        )


def test_registry_is_namespaced_by_scope_and_deterministically_ordered() -> None:
    registry = CommandRegistry()
    registry.register(_definition("zeta"))
    registry.register(_definition("alpha"))
    registry.register(_definition("alpha", scope=CommandScope.ADMIN))

    assert [value.name for value in registry.definitions(CommandScope.CUSTOMER)] == [
        "alpha",
        "zeta",
    ]
    assert registry.resolve("alpha", CommandScope.ADMIN).scope is CommandScope.ADMIN
    with pytest.raises(CommandError) as scope_error:
        registry.resolve("zeta", CommandScope.ADMIN)
    assert scope_error.value.code == "COMMAND_SCOPE_DENIED"


def test_parser_handles_commands_aliases_arguments_and_non_commands() -> None:
    registry = CommandRegistry()
    registry.register(_definition("help"))
    registry.register(_definition("find", aliases=("lookup",)))

    help_command = parse_command("  /HELP  ", registry, CommandScope.CUSTOMER)
    assert help_command is not None
    assert help_command.canonical_name == "help"
    assert help_command.arguments == ()

    command = parse_command(
        "/LOOKUP   Blue Dream  ", registry, CommandScope.CUSTOMER
    )
    assert command is not None
    assert command.canonical_name == "find"
    assert command.requested_name == "lookup"
    assert command.raw_arguments == "Blue Dream"
    assert command.arguments == ("Blue", "Dream")
    assert parse_command("tell me about Blue Dream", registry, CommandScope.CUSTOMER) is None


@pytest.mark.parametrize("value", ["/", "/ help", "//help", "/help?"])
def test_parser_rejects_empty_or_malformed_commands(value: str) -> None:
    registry = CommandRegistry()
    registry.register(_definition("help"))
    with pytest.raises(CommandError) as error:
        parse_command(value, registry, CommandScope.CUSTOMER)
    assert error.value.code == "COMMAND_INVALID"


def test_parser_rejects_unknown_commands() -> None:
    registry = CommandRegistry()
    with pytest.raises(CommandError) as error:
        parse_command("/missing", registry, CommandScope.CUSTOMER)
    assert error.value.code == "COMMAND_NOT_FOUND"
