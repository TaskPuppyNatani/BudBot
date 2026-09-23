"""M4 execution, availability, permission, and compliance behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from budbot.commands.bootstrap import ADMIN_HELP_PERMISSION, build_command_executor
from budbot.commands.types import (
    CommandArguments,
    CommandDefinition,
    CommandExecutionContext,
    CommandResult,
    CommandScope,
    ParsedCommand,
    PermissionContext,
)
from budbot.compliance.registry import ComplianceCapability
from budbot.core.exceptions import CommandError, ComplianceError, ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.session import AgeAttestationRequest, CustomerSessionCreate
from budbot.services.session_service import SessionService


async def _ok(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    return CommandResult(parsed.canonical_name, parsed.requested_name, parsed.raw_arguments or "ok")


async def _customer_context(
    db_session,
    *,
    name: str,
    profile_id: str = "general_retail",
    features: frozenset[str] = frozenset(),
) -> tuple[CommandExecutionContext, Business]:
    business = Business(
        display_name=name,
        industry="general_retail",
        compliance_domain=(
            "cannabis" if profile_id == "oregon_cannabis" else "general_retail"
        ),
        compliance_profile_id=profile_id,
        compliance_profile_version="1.0",
    )
    assistant = AssistantConfiguration(
        business=business,
        display_name=f"{name} Guide",
        greeting="Hello",
        fallback_message="Ask a team member.",
        enabled=True,
    )
    db_session.add_all([business, assistant])
    await db_session.flush()
    selected_location_id = None
    if profile_id == "oregon_cannabis":
        location = Location(
            business_id=business.id,
            display_name="Portland",
            address_line_1="1 Main St",
            city="Portland",
            region="Oregon",
            region_code="OR",
            postal_code="97201",
            country="US",
            timezone="America/Los_Angeles",
            active=True,
        )
        db_session.add(location)
        await db_session.flush()
        selected_location_id = location.id
    customer_session = await SessionService(
        db_session, TenantContext(business.id)
    ).create(CustomerSessionCreate(selected_location_id=selected_location_id))
    return (
        CommandExecutionContext(
            session=db_session,
            tenant=TenantContext(business.id),
            scope=CommandScope.CUSTOMER,
            customer_session_id=customer_session.id,
            features=features,
        ),
        business,
    )


async def test_scope_permissions_and_argument_validation_fail_closed(db_session) -> None:
    executor = build_command_executor()
    executor.registry.register(
        CommandDefinition(
            name="echo-test",
            description="Echo one value.",
            scope=CommandScope.CUSTOMER,
            handler=_ok,
            arguments=CommandArguments(help_hint="/echo-test <value>", minimum=1, maximum=1),
        )
    )
    executor.registry.register(
        CommandDefinition(
            name="admin-test",
            description="Admin test.",
            scope=CommandScope.ADMIN,
            handler=_ok,
            required_permissions=frozenset({"admin:test"}),
        )
    )
    customer, _ = await _customer_context(db_session, name="Scope")

    assert (await executor.execute("/echo-test Value", customer)).output == "Value"
    with pytest.raises(CommandError) as arguments:
        await executor.execute("/echo-test", customer)
    assert arguments.value.code == "COMMAND_ARGUMENT_ERROR"
    with pytest.raises(CommandError) as wrong_scope:
        await executor.execute("/admin-test", customer)
    assert wrong_scope.value.code == "COMMAND_SCOPE_DENIED"

    admin = CommandExecutionContext(
        session=db_session,
        tenant=customer.tenant,
        scope=CommandScope.ADMIN,
    )
    with pytest.raises(CommandError) as unauthenticated:
        await executor.execute("/admin-test", admin)
    assert unauthenticated.value.code == "COMMAND_PERMISSION_DENIED"
    with pytest.raises(CommandError) as missing_permission:
        await executor.execute(
            "/admin-test",
            CommandExecutionContext(
                session=db_session,
                tenant=customer.tenant,
                scope=CommandScope.ADMIN,
                permission_context=PermissionContext(authenticated_admin=True),
            ),
        )
    assert missing_permission.value.code == "COMMAND_PERMISSION_DENIED"

    permitted_admin = CommandExecutionContext(
        session=db_session,
        tenant=customer.tenant,
        scope=CommandScope.ADMIN,
        permission_context=PermissionContext(
            authenticated_admin=True,
            permissions=frozenset({"admin:test", ADMIN_HELP_PERMISSION}),
        ),
    )
    assert (await executor.execute("/admin-test", permitted_admin)).output == "ok"
    admin_help = await executor.execute("/help", permitted_admin)
    assert [command.name for command in admin_help.commands] == ["admin-test", "help"]
    assert "echo-test" not in admin_help.output


async def test_help_and_introspection_filter_features_and_use_assistant_name(
    db_session,
) -> None:
    executor = build_command_executor()
    executor.registry.register(
        CommandDefinition(
            name="feature-test",
            description="Feature-backed test.",
            scope=CommandScope.CUSTOMER,
            handler=_ok,
            required_features=frozenset({"faq_enabled"}),
        )
    )
    executor.registry.register(
        CommandDefinition(
            name="help-only-test",
            description="Visible in help, not autocomplete.",
            scope=CommandScope.CUSTOMER,
            handler=_ok,
            autocomplete=False,
        )
    )
    unavailable, _ = await _customer_context(db_session, name="Pine")
    help_result = await executor.execute("/help", unavailable)
    assert help_result.output.startswith("Pine Guide commands:")
    assert [command.name for command in help_result.commands] == [
        "about",
        "age",
        "clear",
        "contact",
        "help",
        "help-only-test",
        "hours",
        "location",
        "locations",
    ]
    detailed = await executor.metadata(unavailable, include_unavailable=True)
    assert [(item.name, item.available) for item in detailed] == [
        ("about", True),
        ("age", True),
        ("clear", True),
        ("contact", True),
        ("directions", False),
        ("faq", False),
        ("feature-test", False),
        ("help", True),
        ("hours", True),
        ("location", True),
        ("locations", True),
        ("payments", False),
        ("policies", False),
    ]
    with pytest.raises(CommandError) as unavailable_error:
        await executor.execute("/feature-test", unavailable)
    assert unavailable_error.value.code == "COMMAND_UNAVAILABLE"

    available = CommandExecutionContext(
        session=db_session,
        tenant=unavailable.tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=unavailable.customer_session_id,
        features=frozenset({"faq_enabled"}),
    )
    available_help = await executor.execute("/help", available)
    assert [command.name for command in available_help.commands] == [
        "about",
        "age",
        "clear",
        "contact",
        "faq",
        "feature-test",
        "help",
        "help-only-test",
        "hours",
        "location",
        "locations",
    ]


async def test_compliance_hook_reuses_m3_engine(db_session) -> None:
    executor = build_command_executor()
    for name, capability in (
        ("public-test", ComplianceCapability.BUSINESS_HOURS),
        ("gated-test", ComplianceCapability.CANNABIS_PRODUCTS),
        ("prohibited-test", ComplianceCapability.MEDICAL_ADVICE),
    ):
        executor.registry.register(
            CommandDefinition(
                name=name,
                description=name,
                scope=CommandScope.CUSTOMER,
                handler=_ok,
                compliance_capability=capability,
            )
        )

    oregon, _ = await _customer_context(
        db_session, name="Oregon", profile_id="oregon_cannabis"
    )
    assert (await executor.execute("/public-test", oregon)).output == "ok"
    with pytest.raises(ComplianceError) as gated:
        await executor.execute("/gated-test", oregon)
    assert gated.value.code == "AGE_VERIFICATION_REQUIRED"

    await SessionService(db_session, oregon.tenant).attest(
        oregon.customer_session_id,
        AgeAttestationRequest(confirmed_21_or_older=True),
    )
    assert (await executor.execute("/gated-test", oregon)).output == "ok"
    with pytest.raises(ComplianceError) as prohibited:
        await executor.execute("/prohibited-test", oregon)
    assert prohibited.value.code == "CAPABILITY_PROHIBITED"

    general, _ = await _customer_context(db_session, name="General")
    with pytest.raises(ComplianceError) as general_denial:
        await executor.execute("/gated-test", general)
    assert general_denial.value.code == "CAPABILITY_PROHIBITED"


async def test_tenant_expiry_and_profile_mismatch_are_not_bypassed(db_session) -> None:
    executor = build_command_executor()
    first, first_business = await _customer_context(db_session, name="First")
    second, _ = await _customer_context(db_session, name="Second")

    cross_tenant = CommandExecutionContext(
        session=db_session,
        tenant=second.tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=first.customer_session_id,
    )
    with pytest.raises(ResourceNotFound) as tenant_error:
        await executor.execute("/help", cross_tenant)
    assert tenant_error.value.code == "SESSION_NOT_FOUND"

    first_business.compliance_profile_id = "oregon_cannabis"
    first_business.compliance_domain = "cannabis"
    await db_session.flush()
    with pytest.raises(ComplianceError) as mismatch:
        await executor.execute("/help", first)
    assert mismatch.value.code == "COMPLIANCE_PROFILE_MISMATCH"

    expiring, _ = await _customer_context(db_session, name="Expired")
    customer_session = await SessionService(db_session, expiring.tenant).get(
        expiring.customer_session_id
    )
    customer_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    with pytest.raises(ComplianceError) as expired:
        await executor.execute("/help", expiring)
    assert expired.value.code == "SESSION_EXPIRED"
