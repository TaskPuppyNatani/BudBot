"""Container liveness and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from budbot.api.dependencies import get_database
from budbot.database.session import Database

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return process liveness without calling external resources."""

    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def readiness(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
) -> Response:
    """Return readiness after a bounded database connectivity check."""

    try:
        await database.ping(
            request.app.state.settings.database_readiness_timeout_seconds
        )
    except (TimeoutError, OSError, SQLAlchemyError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "checks": {"database": "unavailable"},
            },
        )

    return JSONResponse(
        content={"status": "ready", "checks": {"database": "ok"}}
    )
