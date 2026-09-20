"""Business assistant identity and location-level overrides."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from budbot.models.business import Business
    from budbot.models.location import Location


class AssistantConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stable business-wide customer-facing assistant configuration."""

    __tablename__ = "assistant_configurations"

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        unique=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    greeting: Mapped[str] = mapped_column(String(1000), nullable=False)
    fallback_message: Mapped[str] = mapped_column(String(1000), nullable=False)
    avatar_reference: Mapped[str | None] = mapped_column(String(2048))
    primary_color_override: Mapped[str | None] = mapped_column(String(7))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped["Business"] = relationship(
        back_populates="assistant_configuration"
    )


class LocationAssistantOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Nullable fields override non-null business assistant defaults."""

    __tablename__ = "location_assistant_overrides"
    __table_args__ = (
        ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            ondelete="CASCADE",
            name="fk_location_assistant_overrides_location_tenant",
        ),
        UniqueConstraint(
            "location_id", name="uq_location_assistant_overrides_location"
        ),
    )

    business_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    greeting: Mapped[str | None] = mapped_column(String(1000))
    fallback_message: Mapped[str | None] = mapped_column(String(1000))
    enabled: Mapped[bool | None] = mapped_column(Boolean)

    location: Mapped["Location"] = relationship(back_populates="assistant_override")
