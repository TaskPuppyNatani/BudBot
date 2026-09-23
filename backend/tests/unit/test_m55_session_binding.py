"""Session rebinding, protected capability, and age-command M5.5 coverage."""

from dataclasses import replace

import pytest

from budbot.commands.bootstrap import build_command_executor
from budbot.commands.types import (
    CommandDefinition,
    CommandExecutionContext,
    CommandScope,
)
from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.engine import ComplianceEngine
from budbot.compliance.profiles.oregon_cannabis import OREGON_CANNABIS_PROFILE
from budbot.compliance.registry import get_catalog
from budbot.compliance.resolver import ComplianceResolver
from budbot.compliance.types import ComplianceCapability
from budbot.core.exceptions import ComplianceError, ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.session import (
    AgeAttestationRequest,
    CustomerSessionCreate,
    SessionLocationUpdate,
)
from budbot.services.session_service import SessionService


def _location(
    business: Business,
    name: str,
    region_code: str | None,
    *,
    active: bool = True,
) -> Location:
    return Location(
        business_id=business.id,
        display_name=name,
        address_line_1="10 Main St",
        city=name,
        region=name,
        region_code=region_code,
        postal_code="00000",
        country="us",
        timezone="America/Los_Angeles",
        active=active,
    )


async def _cannabis_tenant(db_session):
    business = Business(
        display_name="Multi-state Cannabis",
        industry="dispensary",
        compliance_domain="cannabis",
        compliance_profile_id="oregon_cannabis",
        compliance_profile_version="1.0",
    )
    db_session.add(business)
    await db_session.flush()
    oregon = _location(business, "Portland", "OR")
    salem = _location(business, "Salem", "OR")
    new_mexico = _location(business, "Albuquerque", "NM")
    arizona = _location(business, "Phoenix", "AZ")
    inactive = _location(business, "Closed", "OR", active=False)
    db_session.add_all([oregon, salem, new_mexico, arizona, inactive])
    await db_session.flush()
    return business, oregon, salem, new_mexico, arizona, inactive


async def test_session_creation_snapshots_or_nm_unresolved_and_unsupported(db_session):
    business, oregon, _salem, new_mexico, arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    service = SessionService(db_session, TenantContext(business.id))

    or_session = await service.create(
        CustomerSessionCreate(selected_location_id=oregon.id)
    )
    nm_session = await service.create(
        CustomerSessionCreate(selected_location_id=new_mexico.id)
    )
    no_location = await service.create(CustomerSessionCreate())
    unsupported = await service.create(
        CustomerSessionCreate(selected_location_id=arizona.id)
    )

    assert (or_session.compliance_jurisdiction_code, or_session.compliance_profile_id) == (
        "US-OR",
        "oregon_cannabis",
    )
    assert (
        nm_session.compliance_jurisdiction_code,
        nm_session.compliance_profile_id,
    ) == ("US-NM", "new_mexico_cannabis")
    assert no_location.compliance_resolution_status == "location_required"
    assert no_location.compliance_profile_id is None
    assert AgeGateStatus(no_location.age_gate_status) == AgeGateStatus.REQUIRED_UNVERIFIED
    assert unsupported.compliance_resolution_status == "profile_unavailable"
    assert unsupported.compliance_profile_id is None
    assert AgeGateStatus(unsupported.age_gate_status) == AgeGateStatus.REQUIRED_UNVERIFIED


async def test_location_fingerprint_preserves_same_jurisdiction_and_resets_changes(
    db_session,
):
    business, oregon, salem, new_mexico, _arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    service = SessionService(db_session, TenantContext(business.id))
    customer_session = await service.create(
        CustomerSessionCreate(selected_location_id=oregon.id)
    )
    await service.attest(
        customer_session.id, AgeAttestationRequest(confirmed_21_or_older=True)
    )
    first_attested_at = customer_session.age_attested_at
    oregon_decision = await ComplianceEngine(
        db_session, TenantContext(business.id)
    ).authorize(customer_session, ComplianceCapability.CANNABIS_PRODUCTS)
    assert oregon_decision.profile_id == "oregon_cannabis"

    same_jurisdiction = await service.set_location(
        customer_session.id, SessionLocationUpdate(selected_location_id=salem.id)
    )
    assert AgeGateStatus(same_jurisdiction.age_gate_status) == AgeGateStatus.VERIFIED
    assert same_jurisdiction.age_attested_at == first_attested_at

    switched = await service.set_location(
        customer_session.id, SessionLocationUpdate(selected_location_id=new_mexico.id)
    )
    assert switched.compliance_jurisdiction_code == "US-NM"
    assert switched.compliance_profile_id == "new_mexico_cannabis"
    assert AgeGateStatus(switched.age_gate_status) == AgeGateStatus.REQUIRED_UNVERIFIED
    assert switched.age_attested_at is None

    await service.attest(
        switched.id, AgeAttestationRequest(confirmed_21_or_older=True)
    )
    new_mexico_decision = await ComplianceEngine(
        db_session, TenantContext(business.id)
    ).authorize(switched, ComplianceCapability.CANNABIS_PRODUCTS)
    assert new_mexico_decision.profile_id == "new_mexico_cannabis"
    back_to_oregon = await service.set_location(
        switched.id, SessionLocationUpdate(selected_location_id=oregon.id)
    )
    assert AgeGateStatus(back_to_oregon.age_gate_status) == AgeGateStatus.REQUIRED_UNVERIFIED
    assert back_to_oregon.age_attested_at is None


async def test_unsupported_to_supported_rebind_and_tenant_active_checks(db_session):
    business, oregon, _salem, _nm, arizona, inactive = await _cannabis_tenant(
        db_session
    )
    service = SessionService(db_session, TenantContext(business.id))
    unsupported = await service.create(
        CustomerSessionCreate(selected_location_id=arizona.id)
    )
    resolved = await service.set_location(
        unsupported.id, SessionLocationUpdate(selected_location_id=oregon.id)
    )
    assert resolved.compliance_profile_id == "oregon_cannabis"
    assert resolved.compliance_resolution_status == "resolved"
    assert AgeGateStatus(resolved.age_gate_status) == AgeGateStatus.REQUIRED_UNVERIFIED

    other = Business(display_name="Other tenant", industry="retail")
    db_session.add(other)
    await db_session.flush()
    foreign_location = _location(other, "Other", "OR")
    db_session.add(foreign_location)
    await db_session.flush()

    with pytest.raises(ResourceNotFound):
        await service.set_location(
            resolved.id,
            SessionLocationUpdate(selected_location_id=foreign_location.id),
        )
    with pytest.raises(ComplianceError) as inactive_error:
        await service.set_location(
            resolved.id, SessionLocationUpdate(selected_location_id=inactive.id)
        )
    assert inactive_error.value.code == "LOCATION_INACTIVE"


async def test_engine_allows_public_info_but_fails_closed_without_profile(db_session):
    business, _oregon, _salem, _nm, arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    service = SessionService(db_session, TenantContext(business.id))
    no_location = await service.create(CustomerSessionCreate())
    unsupported = await service.create(
        CustomerSessionCreate(selected_location_id=arizona.id)
    )
    engine = ComplianceEngine(db_session, TenantContext(business.id))

    public = await engine.authorize(no_location, ComplianceCapability.LOCATIONS)
    assert public.allowed
    assert public.profile_id is None
    with pytest.raises(ComplianceError) as no_location_error:
        await engine.authorize(no_location, ComplianceCapability.CANNABIS_PRODUCTS)
    assert no_location_error.value.code == "COMPLIANCE_LOCATION_REQUIRED"

    public_unsupported = await engine.authorize(
        unsupported, ComplianceCapability.CONTACT
    )
    assert public_unsupported.allowed
    for capability in (
        ComplianceCapability.CANNABIS_PRODUCTS,
        ComplianceCapability.CANNABIS_SEARCH,
        ComplianceCapability.CANNABIS_DEALS,
    ):
        with pytest.raises(ComplianceError) as unavailable:
            await engine.authorize(unsupported, capability)
        assert unavailable.value.code == "COMPLIANCE_PROFILE_UNAVAILABLE"

    with pytest.raises(ComplianceError) as medical:
        await engine.authorize(unsupported, ComplianceCapability.MEDICAL_ADVICE)
    assert medical.value.code == "CAPABILITY_PROHIBITED"
    with pytest.raises(ComplianceError) as unknown:
        await engine.authorize(unsupported, "unregistered_capability")
    assert unknown.value.code == "UNKNOWN_CAPABILITY"


async def test_profile_version_activation_invalidates_existing_session(db_session):
    business, oregon, _salem, _nm, _arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    customer_session = await SessionService(
        db_session, TenantContext(business.id)
    ).create(CustomerSessionCreate(selected_location_id=oregon.id))
    new_version = replace(OREGON_CANNABIS_PROFILE, version="1.1", active=False)
    active_catalog = get_catalog().with_profile(new_version).activate(
        "oregon_cannabis", "1.1"
    )
    engine = ComplianceEngine(
        db_session,
        TenantContext(business.id),
        resolver=ComplianceResolver(active_catalog),
    )

    with pytest.raises(ComplianceError) as stale:
        await engine.authorize(customer_session, ComplianceCapability.CANNABIS_PRODUCTS)
    assert stale.value.code == "COMPLIANCE_PROFILE_MISMATCH"


async def test_executor_allows_stale_safe_public_recovery_but_rejects_regulated(
    db_session, monkeypatch
):
    business, oregon, _salem, _nm, _arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    tenant = TenantContext(business.id)
    customer_session = await SessionService(db_session, tenant).create(
        CustomerSessionCreate(selected_location_id=oregon.id)
    )
    # Simulate a location jurisdiction change after this session's binding snapshot.
    oregon.region_code = "AZ"
    await db_session.flush()

    executor = build_command_executor()
    engine_authorizations = []
    authorize = ComplianceEngine.authorize

    async def record_authorization(engine, session_or_id, capability):
        engine_authorizations.append(ComplianceCapability(capability))
        return await authorize(engine, session_or_id, capability)

    monkeypatch.setattr(ComplianceEngine, "authorize", record_authorization)
    context = CommandExecutionContext(
        session=db_session,
        tenant=tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=customer_session.id,
    )

    listed = await executor.execute("/locations", context)
    assert "Active locations:" in listed.output
    assert "Albuquerque" in listed.output
    assert "Closed" not in listed.output
    assert engine_authorizations == [ComplianceCapability.LOCATIONS]

    async def must_not_run(_context, _parsed):
        raise AssertionError("a stale regulated command must not execute")

    executor.registry.register(
        CommandDefinition(
            name="regulated-test",
            description="Test a regulated capability.",
            scope=CommandScope.CUSTOMER,
            handler=must_not_run,
            compliance_capability=ComplianceCapability.CANNABIS_PRODUCTS,
        )
    )
    with pytest.raises(ComplianceError) as stale:
        await executor.execute("/regulated-test", context)
    assert stale.value.code == "COMPLIANCE_PROFILE_MISMATCH"
    assert engine_authorizations == [ComplianceCapability.LOCATIONS]


async def test_age_command_reports_nm_and_unresolved_states_without_id_claims(db_session):
    business, _oregon, _salem, new_mexico, arizona, _inactive = await _cannabis_tenant(
        db_session
    )
    tenant = TenantContext(business.id)
    service = SessionService(db_session, tenant)
    nm_session = await service.create(
        CustomerSessionCreate(selected_location_id=new_mexico.id)
    )
    no_location = await service.create(CustomerSessionCreate())
    unsupported = await service.create(
        CustomerSessionCreate(selected_location_id=arizona.id)
    )
    executor = build_command_executor()

    async def run(session):
        return await executor.execute(
            "/age",
            CommandExecutionContext(
                session=db_session,
                tenant=tenant,
                scope=CommandScope.CUSTOMER,
                customer_session_id=session.id,
            ),
        )

    nm_output = (await run(nm_session)).output
    assert "US-NM" in nm_output
    assert "21+ website/session attestation" in nm_output
    assert "not government-ID verification" in nm_output
    assert "does not verify medical eligibility" in nm_output
    assert "choose a location with /locations" in (await run(no_location)).output.lower()
    unsupported_output = (await run(unsupported)).output
    assert "US-AZ" in unsupported_output
    assert "no other jurisdiction's rules are being applied" in unsupported_output
