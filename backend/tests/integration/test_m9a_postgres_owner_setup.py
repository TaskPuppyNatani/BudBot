"""PostgreSQL-only concurrent first-owner setup protection coverage.

Set ``BUDBOT_TEST_POSTGRES_URL`` to an isolated PostgreSQL database migrated to
Alembic head. SQLite does not prove concurrent singleton-row reservation.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.dml import Insert, Update

from budbot.models.auth import AuthSetupState
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from budbot.models.auth import AuditEvent
from budbot.services.owner_setup_service import OwnerSetupError, OwnerSetupService


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
            await connection.execute(select(AuthSetupState.id).limit(1))
    except (OSError, SQLAlchemyError) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL M9A test database is unavailable: {exc}")

    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_concurrent_first_owner_claim_has_one_winner(
    postgres_session_factory,
) -> None:
    _engine, session_factory = postgres_session_factory
    setup_session = session_factory()
    first_business = Business(
        display_name=f"Owner claim A {uuid4()}", industry="general_retail"
    )
    second_business = Business(
        display_name=f"Owner claim B {uuid4()}", industry="general_retail"
    )
    state = await setup_session.get(AuthSetupState, 1)
    assert state is not None, "Alembic head must seed the owner-setup singleton"
    prior_state = state.initialized_at, state.owner_user_id
    state.initialized_at = None
    state.owner_user_id = None
    setup_session.add_all([first_business, second_business])
    await setup_session.commit()

    first_session = session_factory()
    second_session = session_factory()
    first_reserved = asyncio.Event()
    second_attempted = asyncio.Event()
    release_first = asyncio.Event()
    first_execute = first_session.execute
    second_execute = second_session.execute

    async def pause_after_reservation(statement, *args, **kwargs):
        result = await first_execute(statement, *args, **kwargs)
        if isinstance(statement, Update) and statement.table.name == "auth_setup_state":
            first_reserved.set()
            await release_first.wait()
        return result

    async def observe_second_attempt(statement, *args, **kwargs):
        if isinstance(statement, Insert) and statement.table.name == "auth_setup_state":
            second_attempted.set()
        return await second_execute(statement, *args, **kwargs)

    first_session.execute = pause_after_reservation  # type: ignore[method-assign]
    second_session.execute = observe_second_attempt  # type: ignore[method-assign]
    first_email = f"first-{uuid4()}@example.test"
    second_email = f"second-{uuid4()}@example.test"

    async def claim(
        session: AsyncSession, business_id, email: str, display_name: str
    ):
        async with session.begin():
            return await OwnerSetupService(session).initialize_first_owner(
                email=email,
                display_name=display_name,
                password_hash="test-only-hash",
                business_id=business_id,
            )

    first_task = asyncio.create_task(
        claim(
            first_session,
            first_business.id,
            first_email,
            "First Owner",
        )
    )
    second_task = None
    try:
        await asyncio.wait_for(first_reserved.wait(), timeout=5)
        second_task = asyncio.create_task(
            claim(
                second_session,
                second_business.id,
                second_email,
                "Second Owner",
            )
        )
        await asyncio.wait_for(second_attempted.wait(), timeout=5)
        await asyncio.sleep(0)
        assert not second_task.done()

        release_first.set()
        winner = await asyncio.wait_for(first_task, timeout=5)
        with pytest.raises(OwnerSetupError, match="already been initialized"):
            await asyncio.wait_for(second_task, timeout=5)

        membership_count = await setup_session.scalar(
            select(func.count(BusinessMembership.id)).where(
                BusinessMembership.business_id == winner.business_id,
                BusinessMembership.role == "owner",
            )
        )
        assert membership_count == 1
    finally:
        release_first.set()
        if not first_task.done():
            first_task.cancel()
        if second_task is not None and not second_task.done():
            second_task.cancel()
        await asyncio.gather(
            first_task,
            *( [second_task] if second_task is not None else [] ),
            return_exceptions=True,
        )
        cleanup = session_factory()
        try:
            current_state = await cleanup.get(AuthSetupState, 1)
            if current_state is not None:
                current_state.initialized_at, current_state.owner_user_id = prior_state
            user_ids = select(UserAccount.id).where(
                UserAccount.email.in_([first_email, second_email])
            )
            await cleanup.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_user_id.in_(user_ids)
                )
            )
            await cleanup.execute(
                delete(BusinessMembership).where(
                    BusinessMembership.business_id.in_(
                        [first_business.id, second_business.id]
                    )
                )
            )
            await cleanup.execute(
                delete(UserAccount).where(UserAccount.email.in_([first_email, second_email]))
            )
            await cleanup.execute(
                delete(Business).where(
                    Business.id.in_([first_business.id, second_business.id])
                )
            )
            await cleanup.commit()
        finally:
            await cleanup.close()
            await first_session.close()
            await second_session.close()
            await setup_session.close()
