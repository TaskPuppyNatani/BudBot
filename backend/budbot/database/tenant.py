"""Reusable tenant-scoped reads for tenant-owned SQLAlchemy models."""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from budbot.core.exceptions import ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.database.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantScopedRepository(Generic[ModelT]):
    """Build ordinary queries with the tenant predicate already attached."""

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        tenant: TenantContext,
    ) -> None:
        if not hasattr(model, "business_id"):
            raise TypeError("tenant-scoped models must define business_id")
        self.session = session
        self.model = model
        self.tenant = tenant

    def select(self) -> Select[tuple[ModelT]]:
        business_id: InstrumentedAttribute[UUID] = self.model.business_id  # type: ignore[attr-defined]
        return select(self.model).where(business_id == self.tenant.business_id)

    async def get(
        self,
        resource_id: UUID,
        *,
        options: Sequence[Any] = (),
        resource_name: str = "resource",
        for_update: bool = False,
    ) -> ModelT:
        identifier: InstrumentedAttribute[UUID] = self.model.id  # type: ignore[attr-defined]
        statement = self.select().where(identifier == resource_id).options(*options)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        resource = await self.session.scalar(statement)
        if resource is None:
            raise ResourceNotFound(resource_name)
        return resource
