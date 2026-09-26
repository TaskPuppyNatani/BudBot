"""Session-service clock, TTL, and location-lock tests."""

from datetime import UTC, datetime, timedelta

import pytest

from budbot.core.exceptions import ResourceNotFound
from budbot.core.time import ensure_utc
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.business import BusinessUpdate
from budbot.schemas.session import CustomerSessionCreate, SessionLocationUpdate
from budbot.services.business_service import BusinessService
from budbot.services.session_service import SessionService


async def test_session_ttl_is_injected_and_expiry_is_deterministic(db_session) -> None:
    business = Business(display_name="TTL", industry="general_retail")
    db_session.add(business)
    await db_session.flush()
    fixed_now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    customer_session = await SessionService(
        db_session,
        TenantContext(business.id),
        ttl_seconds=60,
        clock=lambda: fixed_now,
    ).create(CustomerSessionCreate())

    assert ensure_utc(customer_session.expires_at) == fixed_now + timedelta(
        seconds=60
    )


async def test_inactive_business_blocks_customer_sessions_and_allows_reactivation(
    db_session,
) -> None:
    business = Business(display_name="Inactive", industry="general_retail")
    db_session.add(business)
    await db_session.flush()
    tenant = TenantContext(business.id)
    service = SessionService(db_session, tenant)
    existing_session = await service.create(CustomerSessionCreate())

    business.active = False
    await db_session.flush()

    with pytest.raises(ResourceNotFound) as create_error:
        await service.create(CustomerSessionCreate())
    assert create_error.value.code == "BUSINESS_NOT_FOUND"

    with pytest.raises(ResourceNotFound) as use_error:
        await service.get(existing_session.id)
    assert use_error.value.code == "BUSINESS_NOT_FOUND"

    with pytest.raises(ResourceNotFound) as unbound_error:
        await service.get(existing_session.id, validate_binding=False)
    assert unbound_error.value.code == "BUSINESS_NOT_FOUND"

    reactivated = await BusinessService(db_session).update(
        tenant, business.id, BusinessUpdate(active=True)
    )
    assert reactivated.active is True
    assert await service.get(existing_session.id) == existing_session
    assert await service.create(CustomerSessionCreate())


async def test_session_location_selection_requests_a_tenant_scoped_row_lock(
    db_session, monkeypatch
) -> None:
    business = Business(display_name="Locked", industry="general_retail")
    db_session.add(business)
    await db_session.flush()
    location = Location(
        business_id=business.id,
        display_name="Main",
        address_line_1="1 Main Street",
        city="Portland",
        region="OR",
        postal_code="97201",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add(location)
    await db_session.flush()

    service = SessionService(db_session, TenantContext(business.id), ttl_seconds=60)
    customer_session = await service.create(CustomerSessionCreate())

    original_get = service.locations.get
    calls: list[dict[str, object]] = []

    async def observed_get(resource_id, **kwargs):
        calls.append(kwargs)
        return await original_get(resource_id, **kwargs)

    monkeypatch.setattr(service.locations, "get", observed_get)
    selected = await service.set_location(
        customer_session.id,
        SessionLocationUpdate(selected_location_id=location.id),
    )

    assert selected.selected_location_id == location.id
    assert calls == [{"resource_name": "location", "for_update": True}]


async def test_location_switch_rechecks_business_active_after_locked_lookup(
    db_session, monkeypatch
) -> None:
    business = Business(display_name="Switch race", industry="general_retail")
    original_location = Location(
        business=business,
        display_name="Original",
        address_line_1="1 Main Street",
        city="Portland",
        region="OR",
        postal_code="97201",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    target_location = Location(
        business=business,
        display_name="Target",
        address_line_1="2 Main Street",
        city="Portland",
        region="OR",
        postal_code="97201",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add_all([business, original_location, target_location])
    await db_session.flush()

    service = SessionService(db_session, TenantContext(business.id), ttl_seconds=60)
    customer_session = await service.create(
        CustomerSessionCreate(selected_location_id=original_location.id)
    )
    original_lookup = BusinessService.get_for_customer
    lookup_modes: list[bool] = []

    async def deactivate_between_lookups(
        business_service,
        tenant,
        business_id,
        *,
        for_update: bool = False,
    ):
        lookup_modes.append(for_update)
        if for_update:
            assert business.active is False
            return await original_lookup(
                business_service, tenant, business_id, for_update=True
            )

        result = await original_lookup(business_service, tenant, business_id)
        business.active = False
        await db_session.flush()
        return result

    monkeypatch.setattr(
        BusinessService, "get_for_customer", deactivate_between_lookups
    )

    with pytest.raises(ResourceNotFound) as error:
        await service.set_location(
            customer_session.id,
            SessionLocationUpdate(selected_location_id=target_location.id),
        )

    assert error.value.code == "BUSINESS_NOT_FOUND"
    assert lookup_modes == [False, True]
    await db_session.refresh(customer_session)
    assert customer_session.selected_location_id == original_location.id
