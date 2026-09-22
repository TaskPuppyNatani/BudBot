"""Business tenant model."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from budbot.models.assistant import AssistantConfiguration
    from budbot.models.location import Location
    from budbot.models.session import CustomerSession
    from budbot.models.user import BusinessMembership


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Top-level tenant and security boundary."""

    __tablename__ = "businesses"

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(250))
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    main_phone: Mapped[str | None] = mapped_column(String(40))
    logo_reference: Mapped[str | None] = mapped_column(String(2048))
    primary_brand_color: Mapped[str | None] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_timezone: Mapped[str | None] = mapped_column(String(100))
    compliance_profile_id: Mapped[str] = mapped_column(
        String(100),
        default="general_retail",
        server_default="general_retail",
        nullable=False,
    )
    compliance_profile_version: Mapped[str] = mapped_column(
        String(50),
        default="1.0",
        server_default="1.0",
        nullable=False,
    )

    locations: Mapped[list["Location"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    assistant_configuration: Mapped["AssistantConfiguration"] = relationship(
        back_populates="business",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )
    memberships: Mapped[list["BusinessMembership"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    customer_sessions: Mapped[list["CustomerSession"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
