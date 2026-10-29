"""PostgreSQL serialization coverage for team owner mutations."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import Select

from budbot.core.exceptions import DomainError
from budbot.models.auth import AuditEvent
from budbot.models.business import Business
from budbot.models.invitation import BusinessInvitation
from budbot.models.user import BusinessMembership, UserAccount
from budbot.services.team_service import TeamService


@pytest.fixture
async def postgres_team_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("BUDBOT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BUDBOT_TEST_POSTGRES_URL is not configured")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            await connection.execute(select(BusinessInvitation.id).limit(1))
    except (OSError, SQLAlchemyError) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL M9B team test database is unavailable: {exc}")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed(session: AsyncSession):
    suffix = uuid4().hex
    business = Business(display_name=f"Team concurrency {suffix}", industry="general_retail")
    first = UserAccount(email=f"owner-a-{suffix}@example.test", display_name="Owner A", password_hash="test-hash", active=True)
    second = UserAccount(email=f"owner-b-{suffix}@example.test", display_name="Owner B", password_hash="test-hash", active=True)
    session.add_all([business, first, second]); await session.flush()
    first_membership = BusinessMembership(user_id=first.id, business_id=business.id, role="owner")
    second_membership = BusinessMembership(user_id=second.id, business_id=business.id, role="owner")
    session.add_all([first_membership, second_membership]); await session.commit()
    return business, first, second, first_membership, second_membership


async def _cleanup(factory, business_id, user_ids):
    async with factory() as cleanup:
        await cleanup.execute(delete(AuditEvent).where(AuditEvent.business_id == business_id))
        await cleanup.execute(delete(BusinessInvitation).where(BusinessInvitation.business_id == business_id))
        await cleanup.execute(delete(BusinessMembership).where(BusinessMembership.business_id == business_id))
        await cleanup.execute(delete(Business).where(Business.id == business_id))
        await cleanup.execute(delete(UserAccount).where(UserAccount.id.in_(user_ids)))
        await cleanup.commit()


async def test_concurrent_self_demotions_cannot_remove_the_final_owner(postgres_team_sessions):
    factory = postgres_team_sessions
    setup = factory()
    business, first, second, first_membership, second_membership = await _seed(setup)
    await setup.close()
    first_session, second_session = factory(), factory()
    created_user_id = None

    async def demote_self(session, actor_id, membership_id):
        async with session.begin():
            await TeamService(session).change_role(business.id, actor_id, membership_id, "viewer")

    try:
        outcomes = await asyncio.gather(
            demote_self(first_session, first.id, first_membership.id),
            demote_self(second_session, second.id, second_membership.id),
            return_exceptions=True,
        )
        assert sum(outcome is None for outcome in outcomes) == 1
        rejected = [outcome for outcome in outcomes if isinstance(outcome, DomainError)]
        assert len(rejected) == 1 and rejected[0].status_code == 409
        async with factory() as verify:
            owner_count = await verify.scalar(
                select(func.count()).select_from(BusinessMembership)
                .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
                .where(BusinessMembership.business_id == business.id,
                       BusinessMembership.role == "owner", UserAccount.active.is_(True))
            )
            assert owner_count == 1
    finally:
        await first_session.close(); await second_session.close()
        await _cleanup(factory, business.id, [first.id, second.id])


async def test_owner_is_rechecked_after_waiting_for_business_lock(postgres_team_sessions):
    factory = postgres_team_sessions
    setup = factory()
    business, first, second, first_membership, second_membership = await _seed(setup)
    third = UserAccount(
        email=f"team-member-{uuid4().hex}@example.test", display_name="Team Member",
        password_hash="test-hash", active=True,
    )
    setup.add(third); await setup.flush()
    target = BusinessMembership(user_id=third.id, business_id=business.id, role="manager")
    setup.add(target); await setup.commit()
    target_id, third_id = target.id, third.id
    await setup.close()
    blocker, waiting = factory(), factory()
    entered = asyncio.Event()
    original_scalar = waiting.scalar

    async def observe_locked_business(statement, *args, **kwargs):
        if isinstance(statement, Select) and statement._for_update_arg is not None:
            entered.set()
        return await original_scalar(statement, *args, **kwargs)

    waiting.scalar = observe_locked_business  # type: ignore[method-assign]
    task = None
    try:
        await blocker.begin()
        await blocker.execute(select(Business).where(Business.id == business.id).with_for_update())
        locked_membership = await blocker.scalar(
            select(BusinessMembership).where(
                BusinessMembership.id == second_membership.id
            ).with_for_update()
        )
        assert locked_membership is not None
        locked_membership.role = "viewer"
        await blocker.flush()
        # Model the permission dependency having loaded this row before the
        # request waits for the business lock.
        preloaded_actor = await waiting.scalar(
            select(BusinessMembership).where(
                BusinessMembership.id == second_membership.id
            )
        )
        assert preloaded_actor is not None
        task = asyncio.create_task(TeamService(waiting).change_role(
            business.id, second.id, target_id, "viewer"
        ))
        await asyncio.wait_for(entered.wait(), timeout=5)
        await blocker.commit()
        with pytest.raises(DomainError) as raised:
            await asyncio.wait_for(task, timeout=5)
        assert raised.value.status_code == 403
    finally:
        if blocker.in_transaction():
            await blocker.rollback()
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await blocker.close(); await waiting.close()
        await _cleanup(factory, business.id, [first.id, second.id, third_id])


async def test_competing_invitation_accepts_have_one_winner(postgres_team_sessions):
    factory = postgres_team_sessions
    setup = factory()
    business, owner, other_owner, *_ = await _seed(setup)
    token = None
    try:
        invitation, token = await TeamService(setup).create_invitation(
            business.id, owner.id, "new-teammate@example.test", "manager"
        )
        await setup.commit()
        invitation_id = invitation.id
    finally:
        await setup.close()

    first_session, second_session = factory(), factory()

    async def accept(session):
        async with session.begin():
            await TeamService(session).accept_new_account(
                token, "New Teammate", "a-safe-new-passphrase", "198.51.100.27"
            )

    try:
        outcomes = await asyncio.gather(
            accept(first_session), accept(second_session), return_exceptions=True
        )
        assert sum(outcome is None for outcome in outcomes) == 1
        failures = [outcome for outcome in outcomes if isinstance(outcome, DomainError)]
        assert len(failures) == 1 and failures[0].status_code == 404
        async with factory() as verify:
            invite = await verify.get(BusinessInvitation, invitation_id)
            account = await verify.scalar(
                select(UserAccount).where(UserAccount.email == "new-teammate@example.test")
            )
            created_user_id = account.id if account else None
            memberships = list((await verify.scalars(
                select(BusinessMembership).where(
                    BusinessMembership.business_id == business.id,
                    BusinessMembership.user_id == account.id,
                )
            )).all()) if account else []
            assert invite is not None and invite.accepted_at is not None
            assert account is not None and len(memberships) == 1
            assert memberships[0].role == "manager"
    finally:
        await first_session.close(); await second_session.close()
        await _cleanup(
            factory, business.id,
            [user_id for user_id in (owner.id, other_owner.id, created_user_id) if user_id is not None],
        )
