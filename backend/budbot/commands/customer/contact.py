"""Public location contact details with business-wide phone fallback."""

from budbot.commands.customer.common import command_result, get_selected_location
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.services.customer_information_service import CustomerInformationService


async def contact(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    location = await get_selected_location(context)
    assert location is not None
    details = await CustomerInformationService(
        context.session, context.tenant
    ).resolve_contact(location)
    lines = [f"Public contact for {location.display_name}:"]
    if details.address:
        lines.append(f"Address: {details.address}")
    if details.phone:
        lines.append(f"Phone: {details.phone}")
    if details.website:
        lines.append(f"Website: {details.website}")
    if len(lines) == 1:
        return command_result(parsed, f"No public contact information is configured for {location.display_name}.")
    return command_result(parsed, "\n".join(lines))
