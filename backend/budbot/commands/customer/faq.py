"""Deterministic business-managed FAQ list and search command."""

from budbot.commands.customer.common import command_result, get_selected_location
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.core.exceptions import CommandError
from budbot.services.knowledge_service import KnowledgeService


async def faq(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    location = await get_selected_location(context, required=False)
    location_id = location.id if location is not None else None
    service = KnowledgeService(context.session, context.tenant)
    query = " ".join(parsed.arguments).strip()
    if not query:
        entries = await service.public_faqs(location_id)
        if not entries:
            return command_result(parsed, "No public FAQs are configured.")
        heading = (
            "Public FAQs:"
            if location is None
            else f"Public FAQs for {location.display_name}:"
        )
        return command_result(
            parsed, "\n".join([heading, *(f"- {entry.question}" for entry in entries[:20])])
        )

    matches = await service.search_public_faqs(location_id, query)
    if not matches:
        raise CommandError(
            "FAQ_NOT_FOUND", "No public FAQ matched that search.", status_code=404
        )
    lines: list[str] = []
    for entry in matches[:10]:
        lines.extend((f"Q: {entry.question}", f"A: {entry.answer}", ""))
    if len(matches) > 10:
        lines.append("More matches are available; narrow the search terms.")
    return command_result(parsed, "\n".join(lines).rstrip())
