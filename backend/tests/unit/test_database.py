"""SQLAlchemy foundation tests that do not require a live database."""

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.config import Settings
from budbot.database.session import Database


async def test_database_builds_async_session_factory() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+asyncpg://budbot:test@localhost:5432/budbot_test",
    )
    database = Database(settings)

    try:
        async with database.session_factory() as session:
            assert isinstance(session, AsyncSession)
    finally:
        await database.dispose()
