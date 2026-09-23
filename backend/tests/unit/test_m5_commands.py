"""End-to-end behavior for the M5 customer information commands."""

from datetime import time

import pytest
from pydantic import ValidationError

from budbot.commands.bootstrap import build_command_executor
from budbot.commands.types import CommandExecutionContext, CommandScope
from budbot.compliance.age_gate import AgeGateStatus
from budbot.core.exceptions import CommandError
from budbot.core.tenancy import TenantContext
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.models.knowledge import FAQEntry
from budbot.models.location import Location, LocationHours
from budbot.schemas.business import StorePolicy
from budbot.schemas.session import AgeAttestationRequest, CustomerSessionCreate
from budbot.services.session_service import SessionService


async def _context(db_session, *, profile_id: str = "general_retail"):
    business = Business(
        display_name="Cedar Shop",
        industry="general_retail",
        compliance_profile_id=profile_id,
        compliance_profile_version="1.0",
        main_phone="503-555-0100",
        website_url="https://cedar.example",
        payment_methods=[{"name": "Cash"}, {"name": "Debit", "details": "PIN required"}],
        store_policies=[{"title": "Returns", "text": "Receipt required."}],
    )
    assistant = AssistantConfiguration(
        business=business,
        display_name="Cedar Guide",
        greeting="Welcome",
        fallback_message="Ask our team.",
        enabled=True,
    )
    db_session.add_all([business, assistant])
    await db_session.flush()

    def make_location(name: str, *, active: bool = True, phone: str | None = None):
        return Location(
            business_id=business.id,
            display_name=name,
            address_line_1="10 Main St",
            city="Portland",
            region="OR",
            postal_code="97201",
            country="US",
            phone=phone,
            timezone="America/Los_Angeles",
            active=active,
        )

    selected_location = make_location("Hawthorne", phone="971-555-0101")
    pearl_one = make_location("Pearl")
    pearl_two = make_location("Pearl")
    inactive = make_location("Closed Shop", active=False)
    db_session.add_all([selected_location, pearl_one, pearl_two, inactive])
    other_business = Business(display_name="Other", industry="general_retail")
    db_session.add(other_business)
    await db_session.flush()
    db_session.add(
        FAQEntry(
            business_id=other_business.id,
            question="Secret question",
            answer="Other tenant data.",
        )
    )
    db_session.add_all(
        [
            LocationHours(
                business_id=business.id,
                location_id=selected_location.id,
                day_of_week=0,
                open_time=time(9),
                close_time=time(17),
                is_closed=False,
            ),
            LocationHours(
                business_id=business.id,
                location_id=selected_location.id,
                day_of_week=1,
                open_time=None,
                close_time=None,
                is_closed=True,
            ),
            FAQEntry(
                business_id=business.id,
                question="What are the hours?",
                answer="Business-wide answer.",
            ),
            FAQEntry(
                business_id=business.id,
                location_id=selected_location.id,
                question="What are the hours?",
                answer="Hawthorne-specific answer.",
            ),
            FAQEntry(
                business_id=business.id,
                question="How do I park?",
                answer="Use the rear lot.",
                enabled=False,
            ),
            FAQEntry(
                business_id=business.id,
                question="Private question",
                answer="Do not expose.",
                is_public=False,
            ),
        ]
    )
    await db_session.flush()
    tenant = TenantContext(business.id)
    customer_session = await SessionService(db_session, tenant).create(
        CustomerSessionCreate()
    )
    context = CommandExecutionContext(
        session=db_session,
        tenant=tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=customer_session.id,
    )
    return context, business, selected_location


async def test_customer_information_commands_are_deterministic_and_tenant_scoped(
    db_session,
) -> None:
    context, business, location = await _context(db_session)
    executor = build_command_executor()

    listed = await executor.execute("/locations", context)
    assert listed.output.index("Hawthorne") < listed.output.index("Pearl")
    assert "Closed Shop" not in listed.output
    assert "Secret" not in listed.output
    with pytest.raises(CommandError) as ambiguous:
        await executor.execute("/location Pearl", context)
    assert ambiguous.value.code == "LOCATION_AMBIGUOUS"
    with pytest.raises(CommandError) as inactive:
        await executor.execute("/location Closed Shop", context)
    assert inactive.value.code == "LOCATION_NOT_FOUND"
    with pytest.raises(CommandError) as other_tenant:
        await executor.execute("/location Secret", context)
    assert other_tenant.value.code == "LOCATION_NOT_FOUND"

    selected = await executor.execute("/location   hAWTHORNE ", context)
    assert selected.output == "Selected location: Hawthorne — Portland, OR."
    current = await executor.execute("/location", context)
    assert "Selected location: Hawthorne" in current.output
    hours = await executor.execute("/hours", context)
    assert "Monday: 9:00 AM–5:00 PM" in hours.output
    assert "Tuesday: Closed" in hours.output
    alias_hours = await executor.execute("/open", context)
    assert alias_hours.canonical_name == "hours"
    assert alias_hours.output == hours.output
    alias_closing = await executor.execute("/closing", context)
    assert alias_closing.canonical_name == "hours"
    assert alias_closing.output == hours.output

    directions = await executor.execute("/map", context)
    assert directions.canonical_name == "directions"
    assert "10 Main St, Portland, OR 97201, US" in directions.output
    assert "%20" in directions.output
    alias_address = await executor.execute("/address", context)
    assert alias_address.canonical_name == "directions"
    assert alias_address.output == directions.output
    contact = await executor.execute("/contact", context)
    assert "971-555-0101" in contact.output
    assert "503-555-0100" not in contact.output
    assert "https://cedar.example" in contact.output

    faq_index = await executor.execute("/faq", context)
    assert faq_index.output.count("What are the hours?") == 1
    assert "How do I park?" not in faq_index.output
    assert "Private question" not in faq_index.output
    assert "Secret question" not in faq_index.output
    answer = await executor.execute("/faq WHAT are the HOURS?", context)
    assert "Hawthorne-specific answer." in answer.output
    with pytest.raises(CommandError) as missing_faq:
        await executor.execute("/faq no matching entry", context)
    assert missing_faq.value.code == "FAQ_NOT_FOUND"

    assert "Cash" in (await executor.execute("/payments", context)).output
    assert "Receipt required." in (await executor.execute("/policies", context)).output
    age = await executor.execute("/age", context)
    assert "general_retail" in age.output
    assert "does not require a cannabis age attestation" in age.output
    assert "Session status: no age attestation is required." in age.output
    about = await executor.execute("/about", context)
    assert "Cedar Guide" in about.output
    assert "BudBot" not in about.output
    assert "/products" not in about.output
    clear = await executor.execute("/clear", context)
    assert "nothing to clear" in clear.output
    customer_session = await SessionService(context.session, context.tenant).get(
        context.customer_session_id
    )
    assert customer_session.selected_location_id == location.id
    assert customer_session.age_gate_status == AgeGateStatus.NOT_REQUIRED

    business.directions_enabled = False
    await context.session.flush()
    available = await executor.metadata(context)
    assert "directions" not in {item.name for item in available}
    with pytest.raises(CommandError) as disabled:
        await executor.execute("/directions", context)
    assert disabled.value.code == "COMMAND_UNAVAILABLE"
    assert business.id == context.tenant.business_id


async def test_oregon_age_information_is_public_and_uses_profile_notices(db_session) -> None:
    context, _business, _location = await _context(
        db_session, profile_id="oregon_cannabis"
    )
    executor = build_command_executor()

    before = await executor.execute("/age", context)
    assert "21+ website/session attestation" in before.output
    assert "not government-ID verification" in before.output
    assert "qualifying OMMP pathways" in before.output
    assert "has not been completed" in before.output
    assert (
        "Session status: the age attestation has not been "
        "completed." in before.output
    )

    await SessionService(context.session, context.tenant).attest(
        context.customer_session_id,
        AgeAttestationRequest(confirmed_21_or_older=True),
    )
    after = await executor.execute("/age", context)
    assert "website/session attestation recorded" in after.output
    assert "Session status: website/session attestation recorded." in after.output
    await executor.execute("/clear", context)
    customer_session = await SessionService(context.session, context.tenant).get(
        context.customer_session_id
    )
    assert customer_session.age_gate_status == AgeGateStatus.VERIFIED
    assert customer_session.compliance_profile_id == "oregon_cannabis"

async def test_global_faq_is_stable_when_selected_location_has_no_override(
    db_session,
) -> None:
    context, business, _location = await _context(db_session)
    context.session.add(
        FAQEntry(
            business_id=business.id,
            question="Where can I park?",
            answer="Parking is available behind the store.",
        )
    )
    await context.session.flush()
    executor = build_command_executor()

    without_location = await executor.execute("/faq where can I park", context)
    await executor.execute("/location Hawthorne", context)
    with_location = await executor.execute("/faq where can I park", context)

    assert with_location.output == without_location.output
    assert "Parking is available behind the store." in with_location.output


async def test_duplicate_public_faqs_are_rejected_within_each_scope(
    db_session,
) -> None:
    context, business, _location = await _context(db_session)
    executor = build_command_executor()

    context.session.add(
        FAQEntry(
            business_id=business.id,
            question="  WHAT are   the HOURS? ",
            answer="Second business-wide answer.",
        )
    )
    await context.session.flush()
    with pytest.raises(CommandError) as duplicate_business_faq:
        await executor.execute("/faq", context)
    assert duplicate_business_faq.value.code == "FAQ_AMBIGUOUS"
    assert duplicate_business_faq.value.status_code == 409

    context, business, location = await _context(db_session)
    executor = build_command_executor()
    context.session.add(
        FAQEntry(
            business_id=business.id,
            location_id=location.id,
            question="what ARE the   hours?",
            answer="Second Hawthorne answer.",
        )
    )
    await context.session.flush()
    await executor.execute("/location Hawthorne", context)
    with pytest.raises(CommandError) as duplicate_location_faq:
        await executor.execute("/faq what are the hours", context)
    assert duplicate_location_faq.value.code == "FAQ_AMBIGUOUS"
    assert duplicate_location_faq.value.status_code == 409


async def test_persisted_information_flags_gate_execution_help_and_autocomplete(
    db_session,
) -> None:
    context, business, _location = await _context(db_session)
    executor = build_command_executor()

    for flag, command in (
        ("faq_enabled", "faq"),
        ("payments_info_enabled", "payments"),
        ("policies_info_enabled", "policies"),
    ):
        setattr(business, flag, False)
        await context.session.flush()

        with pytest.raises(CommandError) as disabled:
            await executor.execute(f"/{command}", context)
        assert disabled.value.code == "COMMAND_UNAVAILABLE"

        help_result = await executor.execute("/help", context)
        assert command not in {item.name for item in help_result.commands}
        autocomplete = await executor.metadata(context)
        assert command not in {item.name for item in autocomplete}


async def test_contact_fallback_and_missing_optional_details_are_honest(
    db_session,
) -> None:
    context, business, location = await _context(db_session)
    executor = build_command_executor()
    await executor.execute("/location Hawthorne", context)

    location.phone = None
    await context.session.flush()
    fallback = await executor.execute("/contact", context)
    assert "Phone: 503-555-0100" in fallback.output

    business.main_phone = None
    business.website_url = None
    await context.session.flush()
    without_optional_details = await executor.execute("/contact", context)
    assert (
        "Address: 10 Main St, Portland, OR 97201, US"
        in without_optional_details.output
    )
    assert "Phone:" not in without_optional_details.output
    assert "Website:" not in without_optional_details.output

    location.address_line_1 = ""
    location.address_line_2 = None
    location.city = ""
    location.region = ""
    location.postal_code = ""
    location.country = ""
    await context.session.flush()
    no_contact = await executor.execute("/contact", context)
    assert no_contact.output == (
        "No public contact information is configured for Hawthorne."
    )


def test_store_policy_rejects_whitespace_only_text() -> None:
    with pytest.raises(ValidationError):
        StorePolicy(title="Returns", text="")
    with pytest.raises(ValidationError):
        StorePolicy(title="Returns", text="   ")
    with pytest.raises(ValidationError):
        StorePolicy(title="Returns", text=" \t\n ")

    policy = StorePolicy(title="Returns", text="  Receipt required.  ")
    assert policy.text == "Receipt required."
