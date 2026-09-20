"""User account and business-membership foundation."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from budbot.models.business import Business


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A future authenticated person, without M2 authentication behavior."""

    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list["BusinessMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class BusinessMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Many-to-many user membership with a minimal future role label."""

    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "business_id", name="uq_business_memberships_user_business"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    user: Mapped["UserAccount"] = relationship(back_populates="memberships")
    business: Mapped["Business"] = relationship(back_populates="memberships")
