"""Safe HTTP translations for expected domain errors."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from budbot.core.exceptions import ResourceNotFound


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResourceNotFound)
    async def resource_not_found(
        request: Request, exc: ResourceNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )
