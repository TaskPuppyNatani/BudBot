"""Asynchronous SQLAlchemy engine and session infrastructure."""

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from budbot.core.config import Settings


class Database:
    """Own the application database engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            connect_args={
                "timeout": settings.database_connect_timeout_seconds,
                "server_settings": {"application_name": "budbot"},
            },
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one request-scoped session."""

        async with self.session_factory() as session:
            yield session

    async def ping(self, timeout_seconds: float) -> None:
        """Verify database connectivity within a hard upper time bound."""

        async with asyncio.timeout(timeout_seconds):
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """Release pooled database connections during application shutdown."""

        await self.engine.dispose()
