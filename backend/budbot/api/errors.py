"""Safe HTTP translations for expected domain errors."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from budbot.core.exceptions import DomainError


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(
        request: Request, exc: DomainError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
