"""Session-service clock, TTL, and location-lock tests."""

from datetime import UTC, datetime, timedelta

from budbot.core.time import ensure_utc
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.session import CustomerSessionCreate, SessionLocationUpdate
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
