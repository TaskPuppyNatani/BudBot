"""Explicit M5 customer-command registrations."""

from budbot.commands.executor import CommandExecutor
from budbot.commands.registry import CommandRegistry
from budbot.commands.types import (
    CommandArguments,
    CommandDefinition,
    CommandHandler,
    CommandScope,
)
from budbot.compliance.registry import ComplianceCapability
from budbot.commands.customer.about import create_about_handler
from budbot.commands.customer.age import age
from budbot.commands.customer.clear import clear
from budbot.commands.customer.contact import contact
from budbot.commands.customer.directions import directions
from budbot.commands.customer.faq import faq
from budbot.commands.customer.hours import hours
from budbot.commands.customer.locations import location, locations
from budbot.commands.customer.payments import payments
from budbot.commands.customer.policies import policies


def _customer(
    name: str,
    description: str,
    handler: CommandHandler,
    *,
    aliases: tuple[str, ...] = (),
    feature: str | None = None,
    compliance: ComplianceCapability | None = None,
    arguments: CommandArguments = CommandArguments(),
) -> CommandDefinition:
    return CommandDefinition(
        name=name,
        description=description,
        scope=CommandScope.CUSTOMER,
        handler=handler,
        aliases=aliases,
        arguments=arguments,
        required_features=frozenset({feature}) if feature else frozenset(),
        compliance_capability=compliance,
    )


def register_customer_commands(
    registry: CommandRegistry, executor: CommandExecutor
) -> None:
    definitions = (
        _customer(
            "hours", "Show regular weekly hours for the selected location.", hours,
            aliases=("open", "closing"),
            compliance=ComplianceCapability.BUSINESS_HOURS,
        ),
        _customer(
            "locations", "List active business locations.", locations,
            compliance=ComplianceCapability.LOCATIONS,
        ),
        _customer(
            "location", "Show or select the current location.", location,
            arguments=CommandArguments(
                help_hint="/location <exact active location name>",
                minimum=0,
                maximum=None,
            ),
            compliance=ComplianceCapability.LOCATIONS,
        ),
        _customer(
            "directions", "Show address and a directions link.", directions,
            aliases=("map", "address"),
            feature="directions_enabled",
            compliance=ComplianceCapability.LOCATIONS,
        ),
        _customer(
            "contact", "Show public contact details for the selected location.", contact,
            compliance=ComplianceCapability.CONTACT,
        ),
        _customer(
            "faq", "Browse or search public business FAQs.", faq,
            feature="faq_enabled",
            arguments=CommandArguments(
                help_hint="/faq <search terms>", minimum=0, maximum=None
            ),
        ),
        _customer(
            "payments", "Show configured payment methods.", payments,
            feature="payments_info_enabled",
        ),
        _customer(
            "policies", "Show configured customer-facing policies.", policies,
            feature="policies_info_enabled",
        ),
        _customer(
            "age", "Explain the active age profile and this session's status.", age,
            compliance=ComplianceCapability.AGE_INFORMATION,
        ),
        _customer(
            "clear", "Clear conversation history when such history exists.", clear,
        ),
    )
    for definition in definitions:
        registry.register(definition)
    registry.register(
        _customer(
            "about",
            "Describe this assistant and commands currently available.",
            create_about_handler(executor),
        )
    )
