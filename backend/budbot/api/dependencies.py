"""FastAPI dependencies for application-owned resources."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.database.session import Database


async def get_database(request: Request) -> Database:
    """Return the database owned by the current application lifespan."""

    return request.app.state.database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one SQLAlchemy session for a request."""

    database = await get_database(request)
    async for session in database.session():
        yield session
