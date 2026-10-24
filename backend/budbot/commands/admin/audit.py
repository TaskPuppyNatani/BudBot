"""Bounded history rendered only from the existing sanitized read projection."""

import json

from budbot.commands.admin.common import result
from budbot.core.exceptions import CommandError
from budbot.services.audit_service import AuditHistoryService


async def audit(context, parsed):
    try:
        limit = int(parsed.raw_arguments) if parsed.raw_arguments else 10
        if not 1 <= limit <= 50:
            raise ValueError()
    except ValueError:
        raise CommandError("COMMAND_ARGUMENT_ERROR", "Use /audit [1-50].") from None
    history = await AuditHistoryService(context.session, context.tenant).list_events(limit=limit, offset=0)
    lines = [f"{event.created_at.isoformat()} | {event.event_type} | {json.dumps(event.details, sort_keys=True)}" for event in history.items]
    return result(context, parsed, "\n".join(lines) or "No audit events for this business.")
