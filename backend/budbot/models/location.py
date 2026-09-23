"""Physical locations and normalized weekly hours."""

from datetime import time
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import validates

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from budbot.models.assistant import LocationAssistantOverride
    from budbot.models.business import Business


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical location owned by one business tenant."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_locations_id_business"),
        CheckConstraint(
            "region_code IS NULL OR (length(region_code) = 2 AND region_code = upper(region_code))",
            name="ck_locations_region_code_canonical",
        ),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(250), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(150), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(30), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(40))
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    maps_place_id: Mapped[str | None] = mapped_column(String(255))
    maps_destination: Mapped[str | None] = mapped_column(String(2048))

    @validates("country")
    def normalize_country(self, _key: str, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", normalized):
            raise ValueError("country must be a two-letter code")
        return normalized

    @validates("region_code")
    def normalize_region_code(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", normalized):
            raise ValueError("region_code must be a two-letter canonical code")
        return normalized

    business: Mapped["Business"] = relationship(back_populates="locations")
    hours: Mapped[list["LocationHours"]] = relationship(
        back_populates="location",
        cascade="all, delete-orphan",
        order_by="LocationHours.day_of_week",
    )
    assistant_override: Mapped["LocationAssistantOverride | None"] = relationship(
        back_populates="location",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )


class LocationHours(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One normalized ordinary-hours row per location and weekday."""

    __tablename__ = "location_hours"
    __table_args__ = (
        ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            ondelete="CASCADE",
            name="fk_location_hours_location_tenant",
        ),
        UniqueConstraint(
            "location_id", "day_of_week", name="uq_location_hours_location_day"
        ),
        CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_location_hours_day_of_week",
        ),
        CheckConstraint(
            "(is_closed AND open_time IS NULL AND close_time IS NULL) OR "
            "(NOT is_closed AND open_time IS NOT NULL AND close_time IS NOT NULL "
            "AND open_time < close_time)",
            name="ck_location_hours_valid_range",
        ),
    )

    business_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    location: Mapped["Location"] = relationship(back_populates="hours")
