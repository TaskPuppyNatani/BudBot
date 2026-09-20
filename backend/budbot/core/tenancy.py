"""Request-scoped tenant context without authentication assumptions."""

from dataclasses import dataclass
from uuid import UUID

from budbot.core.exceptions import ResourceNotFound


@dataclass(frozen=True, slots=True)
class TenantContext:
    """The business boundary resolved for one request."""

    business_id: UUID

    def require_business(self, business_id: UUID) -> None:
        """Fail without revealing whether a different tenant exists."""

        if business_id != self.business_id:
            raise ResourceNotFound("business")
