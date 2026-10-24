"""Explicit admin registry layered on the existing help and executor."""

from budbot.commands.admin.audit import audit
from budbot.commands.admin.bot_name import bot_name
from budbot.commands.admin.compliance import compliance
from budbot.commands.admin.enabled import set_enabled
from budbot.commands.admin.greeting import greeting
from budbot.commands.admin.hours_input import HOURS_EXAMPLE
from budbot.commands.admin.knowledge import add_faq, faq
from budbot.commands.admin.locations import hours, location, locations, set_hours
from budbot.commands.admin.provider import provider, test
from budbot.commands.admin.status import preview, status
from budbot.commands.types import CommandArguments, CommandDefinition, CommandScope


def register_admin_commands(registry):
    definitions = (
        ("status", "Show your business and assistant settings.", status, {"business.read", "assistant.read"}, "/status", 0),
        ("locations", "List location names and whether they are active.", locations, {"location.read"}, "/locations", 0),
        ("location", "Choose a location by name, or choose Business defaults in the menu.", location, {"location.read"}, "/location Main", None),
        ("hours", "Show the selected location's weekly hours.", hours, {"location.read"}, "/hours", 0),
        ("set-hours", "Set hours for days or groups; unnamed days stay as they are.", set_hours, {"location.write"}, HOURS_EXAMPLE, None),
        ("bot-name", "Show the assistant name; change it if your account allows.", bot_name, {"assistant.read"}, "/bot-name [name]", None),
        ("greeting", "Show the greeting; change it if your account allows.", greeting, {"assistant.read"}, "/greeting [text]", None),
        ("faq", "Read or search FAQs; use the FAQs page to edit them.", faq, {"faq.read"}, "/faq [query]", None),
        ("add-faq", "Add a customer FAQ for the selected location or Business defaults.", add_faq, {"faq.write"}, '/add-faq Do you have parking? | Street parking only.', None),
        ("disable", "Turn off the assistant here; Business defaults needs --confirm.", set_enabled, {"assistant.write"}, "/disable [--confirm]", 1),
        ("enable", "Turn on the assistant here.", set_enabled, {"assistant.write"}, "/enable", 0),
        ("provider", "Show saved AI provider settings. Use AI Provider to change them.", provider, {"provider.read"}, "/provider", 0),
        ("test", "Check the saved AI connection (a small charge may apply).", test, {"provider.write"}, "/test", 0),
        ("preview", "Open the customer preview.", preview, {"business.read"}, "/preview", 0),
        ("compliance", "Show the customer rules and age requirements.", compliance, {"compliance.read"}, "/compliance", 0),
        ("audit", "Show recent settings changes.", audit, {"audit.read"}, "/audit [1-50]", 1),
    )
    for name, description, handler, permissions, hint, maximum in definitions:
        registry.register(CommandDefinition(name=name, description=description,
            scope=CommandScope.ADMIN, handler=handler,
            required_permissions=frozenset(permissions),
            arguments=CommandArguments(help_hint=hint, maximum=maximum)))
