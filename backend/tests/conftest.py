"""Shared test fixtures for the backend."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from budbot.api.dependencies import get_session
from budbot.core.config import Settings
from budbot.database.base import Base
from budbot.main import create_app
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from budbot.core.security import hash_password
import budbot.models  # noqa: F401

TEST_OWNER_EMAIL = "m9a-owner@example.test"
TEST_OWNER_PASSWORD = "m9a-test-owner-passphrase"
_TEST_OWNER_PASSWORD_HASH = hash_password(TEST_OWNER_PASSWORD)


async def seed_owner(session: AsyncSession) -> tuple[UserAccount, Business]:
    """Create a test owner with one explicit tenant membership."""

    owner = UserAccount(
        email=TEST_OWNER_EMAIL,
        display_name="M9A Test Owner",
        password_hash=_TEST_OWNER_PASSWORD_HASH,
        active=True,
    )
    business = Business(
        display_name="M9A Test Business",
        industry="general_retail",
        default_timezone="UTC",
        assistant_configuration=AssistantConfiguration(
            display_name="Test Assistant",
            greeting="Welcome.",
            fallback_message="Please ask a team member.",
            enabled=True,
        ),
    )
    session.add_all([owner, business])
    await session.flush()
    session.add(
        BusinessMembership(
            user_id=owner.id, business_id=business.id, role="owner"
        )
    )
    await session.commit()
    return owner, business


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+asyncpg://budbot:test@localhost:5432/budbot_test",
        database_readiness_timeout_seconds=0.1,
    )


@pytest.fixture
def application(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(application: FastAPI) -> AsyncIterator[AsyncClient]:
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as test_client:
            yield test_client


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def m2_client(
    application: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    application.dependency_overrides[get_session] = override_session
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as test_client:
            await seed_owner(db_session)
            login = await test_client.post(
                "/api/v1/auth/login",
                json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
            )
            assert login.status_code == 200, login.text
            test_client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            yield test_client
    application.dependency_overrides.clear()
