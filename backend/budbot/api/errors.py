"""Safe HTTP translations for expected domain errors."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from budbot.core.exceptions import DomainError


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path == "/api/v1/auth/login":
            # Pydantic's normal detail includes the rejected `input`; never echo
            # a supplied password back to a caller or into a captured response.
            return JSONResponse(
                status_code=422,
                content={"detail": "Invalid authentication request."},
            )
        safe_errors = [
            {
                key: error[key]
                for key in ("loc", "msg", "type")
                if key in error
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @app.exception_handler(DomainError)
    async def domain_error(
        request: Request, exc: DomainError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
