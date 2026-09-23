"""Business tenant model."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, JSON, String, true
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
    __table_args__ = (
        CheckConstraint(
            "compliance_domain IN ('general_retail', 'cannabis')",
            name="ck_businesses_compliance_domain",
        ),
    )

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(250))
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    main_phone: Mapped[str | None] = mapped_column(String(40))
    logo_reference: Mapped[str | None] = mapped_column(String(2048))
    primary_brand_color: Mapped[str | None] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_timezone: Mapped[str | None] = mapped_column(String(100))
    payment_methods: Mapped[list[dict[str, str | None]] | None] = mapped_column(JSON)
    store_policies: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    directions_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    faq_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    payments_info_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    policies_info_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    products_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    promotions_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
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
    compliance_domain: Mapped[str] = mapped_column(
        String(32),
        default="general_retail",
        server_default="general_retail",
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
