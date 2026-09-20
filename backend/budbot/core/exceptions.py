"""Normalized domain errors safe for API translation."""


class DomainError(Exception):
    """Base class for expected domain failures."""


class ResourceNotFound(DomainError):
    """A resource was absent or outside the active tenant scope."""

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found")
