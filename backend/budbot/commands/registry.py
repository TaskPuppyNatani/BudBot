"""Deterministic command registration and protected-name validation."""

from __future__ import annotations

import re

from budbot.commands.types import (
    CommandDefinition,
    CommandScope,
    CustomCommandDefinition,
)
from budbot.core.exceptions import CommandError


CUSTOMER_BUILTIN_NAMES = frozenset(
    {
        "help",
        "hours",
        "locations",
        "location",
        "directions",
        "contact",
        "faq",
        "products",
        "search",
        "categories",
        "deals",
        "payments",
        "policies",
        "age",
        "clear",
        "about",
    }
)
ADMIN_BUILTIN_NAMES = frozenset(
    {
        "help",
        "status",
        "locations",
        "location",
        "hours",
        "set-hours",
        "bot-name",
        "greeting",
        "faq",
        "add-faq",
        "disable",
        "enable",
        "provider",
        "test",
        "preview",
        "compliance",
        "audit",
    }
)
PROTECTED_BUILTIN_NAMES = CUSTOMER_BUILTIN_NAMES | ADMIN_BUILTIN_NAMES
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class CommandRegistrationError(ValueError):
    """Clear internal configuration failure raised during explicit bootstrap."""


def normalize_command_name(name: str) -> str:
    normalized = name.strip().lower()
    if normalized.startswith("/"):
        normalized = normalized[1:]
    if not _NAME_PATTERN.fullmatch(normalized):
        raise CommandRegistrationError(f"invalid command name: {name!r}")
    return normalized


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[tuple[CommandScope, str], CommandDefinition] = {}
        self._aliases: dict[tuple[CommandScope, str], str] = {}

    def register(self, definition: CommandDefinition) -> None:
        name = normalize_command_name(definition.name)
        aliases = tuple(normalize_command_name(alias) for alias in definition.aliases)
        if len(set(aliases)) != len(aliases) or name in aliases:
            raise CommandRegistrationError("command aliases must be unique")

        keys = (name, *aliases)
        for candidate in keys:
            key = (definition.scope, candidate)
            if key in self._commands or key in self._aliases:
                raise CommandRegistrationError(
                    f"command name or alias already registered: {candidate}"
                )

        normalized = CommandDefinition(
            name=name,
            description=definition.description,
            scope=definition.scope,
            handler=definition.handler,
            aliases=aliases,
            arguments=definition.arguments,
            required_permissions=frozenset(definition.required_permissions),
            required_features=frozenset(definition.required_features),
            compliance_capability=definition.compliance_capability,
            visible=definition.visible,
            autocomplete=definition.autocomplete,
            protected=definition.protected,
        )
        self._commands[(definition.scope, name)] = normalized
        for alias in aliases:
            self._aliases[(definition.scope, alias)] = name

    def resolve(self, name: str, scope: CommandScope) -> CommandDefinition:
        try:
            normalized = normalize_command_name(name)
        except CommandRegistrationError as exc:
            raise CommandError("COMMAND_INVALID", "the command name is malformed") from exc
        canonical = self._aliases.get((scope, normalized), normalized)
        definition = self._commands.get((scope, canonical))
        if definition is not None:
            return definition
        if any(
            key_name == normalized or self._aliases.get((key_scope, normalized))
            for key_scope, key_name in self._commands
            if key_scope is not scope
        ):
            raise CommandError(
                "COMMAND_SCOPE_DENIED",
                "the command is not available in this command scope",
                status_code=403,
            )
        raise CommandError(
            "COMMAND_NOT_FOUND", "the requested command was not found", status_code=404
        )

    def definitions(self, scope: CommandScope) -> tuple[CommandDefinition, ...]:
        return tuple(
            definition
            for (registered_scope, _), definition in sorted(
                self._commands.items(), key=lambda item: item[0][1]
            )
            if registered_scope is scope
        )

    def validate_custom_definition(self, definition: CustomCommandDefinition) -> None:
        """Validate safe declarative names without making them executable."""

        names = (
            normalize_command_name(definition.name),
            *(normalize_command_name(alias) for alias in definition.aliases),
        )
        if len(set(names)) != len(names):
            raise CommandRegistrationError("custom command names must be unique")
        for name in names:
            if name in PROTECTED_BUILTIN_NAMES:
                raise CommandRegistrationError(
                    f"custom command cannot override protected built-in name: {name}"
                )
            if any(key_name == name for _, key_name in self._commands) or any(
                alias == name for _, alias in self._aliases
            ):
                raise CommandRegistrationError(
                    f"custom command name already registered: {name}"
                )
