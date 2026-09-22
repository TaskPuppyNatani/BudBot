"""PostgreSQL-only M3 location-lock coverage.

Set ``BUDBOT_TEST_POSTGRES_URL`` to an isolated PostgreSQL database that is
already migrated to Alembic head to run this test. It is skipped otherwise;
SQLite does not prove PostgreSQL row-lock semantics.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from budbot.core.exceptions import ComplianceError
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.session import CustomerSession
from budbot.schemas.session import CustomerSessionCreate, SessionLocationUpdate
from budbot.services.location_service import LocationService
from budbot.services.session_service import SessionService


@pytest.fixture
async def postgres_session_factory() -> AsyncIterator[
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
]:
    database_url = os.getenv("BUDBOT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BUDBOT_TEST_POSTGRES_URL is not configured")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            await connection.execute(select(CustomerSession.id).limit(1))
    except (OSError, SQLAlchemyError) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL M3 test database is unavailable: {exc}")

    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_deactivation_first_blocks_selection_until_inactive_is_observed(
    postgres_session_factory,
) -> None:
    engine, session_factory = postgres_session_factory
    setup_session = session_factory()
    business = Business(display_name="Concurrency", industry="general_retail")
    setup_session.add(business)
    await setup_session.flush()
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
    setup_session.add(location)
    await setup_session.flush()
    customer_session = await SessionService(
        setup_session,
        TenantContext(business.id),
        ttl_seconds=3600,
    ).create(CustomerSessionCreate())
    await setup_session.commit()

    selection_session = session_factory()
    deactivation_session = session_factory()
    release_deactivation = asyncio.Event()
    deactivation_flushed = asyncio.Event()
    selection_lookup_started = asyncio.Event()

    try:
        deactivation_service = LocationService(
            deactivation_session, TenantContext(business.id)
        )
        original_flush = deactivation_session.flush

        async def observed_flush(*args, **kwargs):
            result = await original_flush(*args, **kwargs)
            deactivation_flushed.set()
            return result

        deactivation_session.flush = observed_flush  # type: ignore[method-assign]

        async def deactivate_and_hold_lock() -> None:
            await deactivation_service.deactivate(location.id)
            await release_deactivation.wait()

        deactivation_task = asyncio.create_task(deactivate_and_hold_lock())
        await asyncio.wait_for(deactivation_flushed.wait(), timeout=5)

        selection_service = SessionService(
            selection_session,
            TenantContext(business.id),
            ttl_seconds=3600,
        )
        original_get = selection_service.locations.get

        async def observed_get(resource_id, **kwargs):
            selection_lookup_started.set()
            return await original_get(resource_id, **kwargs)

        selection_service.locations.get = observed_get  # type: ignore[method-assign]
        selection_task = asyncio.create_task(
            selection_service.set_location(
                customer_session.id,
                SessionLocationUpdate(selected_location_id=location.id),
            )
        )
        await asyncio.wait_for(selection_lookup_started.wait(), timeout=5)
        await asyncio.sleep(0)
        assert not selection_task.done()

        release_deactivation.set()
        await deactivation_task
        await deactivation_session.commit()

        with pytest.raises(ComplianceError) as error:
            await asyncio.wait_for(selection_task, timeout=5)
        assert error.value.code == "LOCATION_INACTIVE"
        await selection_session.rollback()
    finally:
        if "deactivation_task" in locals() and not deactivation_task.done():
            release_deactivation.set()
            deactivation_task.cancel()
            await asyncio.gather(deactivation_task, return_exceptions=True)
        if "selection_task" in locals() and not selection_task.done():
            selection_task.cancel()
            await asyncio.gather(selection_task, return_exceptions=True)
        await selection_session.close()
        await deactivation_session.close()

        cleanup_session = session_factory()
        try:
            await cleanup_session.execute(
                delete(Business).where(Business.id == business.id)
            )
            await cleanup_session.commit()
        finally:
            await cleanup_session.close()
        await setup_session.close()
