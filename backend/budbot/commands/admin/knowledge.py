"""Administrative FAQ reads and the same audited create action as the dashboard."""

from budbot.commands.admin.common import actions, result, runtime, structured_input
from budbot.schemas.knowledge import FAQCreate
from budbot.services.knowledge_service import KnowledgeService, normalize_faq_text


async def faq(context, parsed):
    entries = await KnowledgeService(context.session, context.tenant).list_admin_faqs()
    selected = runtime(context).location_id
    query = normalize_faq_text(parsed.raw_arguments)
    entries = [entry for entry in entries if (selected is None or entry.location_id in {None, selected})
        and (not query or query in normalize_faq_text(entry.question + " " + entry.answer))]
    lines = [f"{entry.id} | scope={entry.location_id or 'business'} | enabled={entry.enabled} | public={entry.is_public}\n{entry.question}\n{entry.answer}" for entry in entries[:25]]
    if len(entries) > 25:
        lines.append("More matches are available in the dashboard.")
    return result(context, parsed, "\n\n".join(lines) or "No matching FAQs. Use the dashboard to edit/disable existing entries.")


async def add_faq(context, parsed):
    payload = structured_input(parsed, FAQCreate,
        allowed={"question", "answer", "location_id", "enabled", "is_public"},
        required={"question", "answer", "location_id"})
    entry = await actions(context).create_faq(payload)
    return result(context, parsed, f"FAQ created: {entry.id} | scope={entry.location_id or 'business'}")
