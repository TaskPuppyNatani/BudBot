"""Configured assistant identity and live command availability."""

from budbot.commands.executor import CommandExecutor
from budbot.commands.types import CommandExecutionContext, CommandHandler, ParsedCommand, CommandResult
from budbot.services.assistant_service import AssistantService
from budbot.services.customer_information_service import CustomerInformationService


def create_about_handler(executor: CommandExecutor) -> CommandHandler:
    async def about(
        context: CommandExecutionContext, parsed: ParsedCommand
    ) -> CommandResult:
        business = await CustomerInformationService(
            context.session, context.tenant
        ).get_business()
        assistants = AssistantService(context.session, context.tenant)
        customer_session = context.customer_session
        if customer_session and customer_session.selected_location_id:
            assistant_name = (
                await assistants.resolve(
                    context.tenant.business_id, customer_session.selected_location_id
                )
            ).display_name
        else:
            assistant_name = (
                await assistants.get(context.tenant.business_id)
            ).display_name
        commands = await executor.metadata(context)
        available = ", ".join(f"/{item.name}" for item in commands)
        output = (
            f"{assistant_name} is the configured assistant for {business.display_name}. "
            f"Available commands: {available}. Run /help for details."
        )
        return CommandResult(
            parsed.canonical_name, parsed.requested_name, output, commands=commands
        )

    return about
