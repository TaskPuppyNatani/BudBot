"""Normalized domain errors safe for API translation."""


class DomainError(Exception):
    """Base class for expected failures that are safe to return to clients."""

    status_code = 400
    code = "DOMAIN_ERROR"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ResourceNotFound(DomainError):
    """A resource was absent or outside the active tenant scope."""

    def __init__(self, resource: str, *, code: str | None = None) -> None:
        normalized_resource = resource.strip().replace(" ", "_").upper()
        super().__init__(
            f"{resource} not found",
            code=code or f"{normalized_resource}_NOT_FOUND",
            status_code=404,
        )


class ComplianceError(DomainError):
    """A deterministic compliance or session-policy denial."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 403,
    ) -> None:
        super().__init__(detail, code=code, status_code=status_code)


class CommandError(DomainError):
    """A normalized parser, registry-resolution, or execution denial."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(detail, code=code, status_code=status_code)
