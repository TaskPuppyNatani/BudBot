"""Explicit admin registry layered on the existing help and executor."""

from budbot.commands.admin.audit import audit
from budbot.commands.admin.bot_name import bot_name
from budbot.commands.admin.compliance import compliance
from budbot.commands.admin.enabled import set_enabled
from budbot.commands.admin.greeting import greeting
from budbot.commands.admin.knowledge import add_faq, faq
from budbot.commands.admin.locations import hours, location, locations, set_hours
from budbot.commands.admin.provider import provider, test
from budbot.commands.admin.status import preview, status
from budbot.commands.types import CommandArguments, CommandDefinition, CommandScope


def register_admin_commands(registry):
    definitions = (
        ("status", "Show business/assistant configuration status.", status, {"business.read", "assistant.read"}, "", 0),
        ("locations", "List this business's locations and UUIDs.", locations, {"location.read"}, "", 0),
        ("location", "Show/select working location; --business selects defaults.", location, {"location.read"}, "/location [name|UUID|--business]", None),
        ("hours", "Show configured weekly hours for the working location.", hours, {"location.read"}, "", 0),
        ("set-hours", "Replace working-location hours using validated JSON.", set_hours, {"location.write"}, '/set-hours {"hours":[{"day_of_week":0,"open_time":"09:00","close_time":"17:00"}]}', None),
        ("bot-name", "Show name; assistant writers may set it in the current scope.", bot_name, {"assistant.read"}, "/bot-name [name]", None),
        ("greeting", "Show greeting; assistant writers may set it in the current scope.", greeting, {"assistant.read"}, "/greeting [text]", None),
        ("faq", "List/search permitted FAQs; edit existing entries in the dashboard.", faq, {"faq.read"}, "/faq [query]", None),
        ("add-faq", "Create a FAQ with explicit business/location scope.", add_faq, {"faq.write"}, '/add-faq {"question":"...","answer":"...","location_id":null}', None),
        ("disable", "Disable assistant in current scope; business default needs --confirm.", set_enabled, {"assistant.write"}, "/disable [--confirm]", 1),
        ("enable", "Enable assistant in current scope.", set_enabled, {"assistant.write"}, "", 0),
        ("provider", "Show safe provider metadata; configure in the dashboard.", provider, {"provider.read"}, "", 0),
        ("test", "Run the bounded saved-provider diagnostic (may incur a small charge).", test, {"provider.write"}, "", 0),
        ("preview", "Provide the separate customer widget preview URL.", preview, {"business.read"}, "", 0),
        ("compliance", "Show effective compliance; mandatory controls remain enforced.", compliance, {"compliance.read"}, "", 0),
        ("audit", "Show recent already-sanitized audit events.", audit, {"audit.read"}, "/audit [1-50]", 1),
    )
    for name, description, handler, permissions, hint, maximum in definitions:
        registry.register(CommandDefinition(name=name, description=description,
            scope=CommandScope.ADMIN, handler=handler,
            required_permissions=frozenset(permissions),
            arguments=CommandArguments(help_hint=hint, maximum=maximum)))
