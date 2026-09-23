"""Configured customer-facing policies; no compliance rules are inferred."""

from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.services.customer_information_service import CustomerInformationService


async def policies(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    business = await CustomerInformationService(
        context.session, context.tenant
    ).get_business()
    configured = business.store_policies
    if configured is None:
        return command_result(parsed, "Customer policies have not been configured.")
    if not configured:
        return command_result(parsed, "No customer policies are currently listed.")
    lines = [f"Customer policies for {business.display_name}:"]
    for policy in configured:
        title = policy.get("title")
        text = policy.get("text")
        if isinstance(title, str) and title.strip() and isinstance(text, str) and text.strip():
            lines.append(f"- {title}: {text}")
    if len(lines) == 1:
        return command_result(parsed, "Customer policies have not been configured.")
    return command_result(parsed, "\n".join(lines))
