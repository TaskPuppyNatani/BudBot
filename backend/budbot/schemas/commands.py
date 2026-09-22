"""Safe M4 command execution and introspection API schemas."""

from uuid import UUID

from pydantic import Field

from budbot.commands.types import CommandScope
from budbot.schemas.common import DomainSchema


class CommandExecuteRequest(DomainSchema):
    session_id: UUID
    input: str = Field(min_length=1, max_length=4096)


class CommandMetadataRead(DomainSchema):
    name: str
    description: str
    aliases: list[str]
    scope: CommandScope
    argument_hint: str
    available: bool


class CommandExecuteRead(DomainSchema):
    canonical_name: str
    requested_name: str
    output: str
    commands: list[CommandMetadataRead] = Field(default_factory=list)
