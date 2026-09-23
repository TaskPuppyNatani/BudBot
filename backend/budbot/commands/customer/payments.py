"""Configured payment-method information; no payment processing."""

from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.services.customer_information_service import CustomerInformationService


async def payments(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    business = await CustomerInformationService(
        context.session, context.tenant
    ).get_business()
    methods = business.payment_methods
    if methods is None:
        return command_result(parsed, "Payment methods have not been configured.")
    if not methods:
        return command_result(parsed, "No payment methods are currently listed.")
    lines = [f"Payment methods for {business.display_name}:"]
    for method in methods:
        name = method.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        details = method.get("details")
        suffix = f" — {details}" if isinstance(details, str) and details else ""
        lines.append(f"- {name}{suffix}")
    if len(lines) == 1:
        return command_result(parsed, "Payment methods have not been configured.")
    return command_result(parsed, "\n".join(lines))
