"""Administrative FAQ reads and the same audited create action as the dashboard."""

from budbot.commands.admin.common import actions, result, runtime, selected_location
from budbot.core.exceptions import CommandError
from budbot.schemas.knowledge import FAQCreate
from budbot.services.knowledge_service import KnowledgeService, normalize_faq_text
from budbot.services.location_service import LocationService


async def faq(context, parsed):
    entries = await KnowledgeService(context.session, context.tenant).list_admin_faqs()
    selected = runtime(context).location_id
    query = normalize_faq_text(parsed.raw_arguments)
    entries = [entry for entry in entries if (selected is None or entry.location_id in {None, selected})
        and (not query or query in normalize_faq_text(entry.question + " " + entry.answer))]
    locations = {item.id: item.display_name for item in await LocationService(context.session, context.tenant).list_locations(include_inactive=True)}
    lines = [f"{entry.question}\n{entry.answer}\nFor: {locations.get(entry.location_id, 'Location no longer listed') if entry.location_id else 'All locations'} — {'Visible to customers' if entry.enabled and entry.is_public else 'Hidden from customers'}" for entry in entries[:25]]
    if len(entries) > 25:
        lines.append("More matches are available in the dashboard.")
    return result(context, parsed, "\n\n".join(lines) or "No matching FAQs. Use the dashboard to edit/disable existing entries.")


async def add_faq(context, parsed):
    question, separator, answer = parsed.raw_arguments.partition("|")
    try:
        if not separator:
            raise ValueError()
        payload = FAQCreate(question=question.strip(), answer=answer.strip(), location_id=runtime(context).location_id)
    except ValueError:
        raise CommandError("COMMAND_ARGUMENT_ERROR",
            "I couldn't understand that FAQ. Try:\n/add-faq Do you have parking? | Street parking only.\n"
            "Put the question before | and the answer after it. Questions can have up to 500 characters; answers up to 10,000.",
            status_code=422) from None
    location = await selected_location(context)
    await actions(context).create_faq(payload)
    return result(context, parsed, f"FAQ added for {location.display_name if location else 'all locations'}.")
