"""Explicit business-managed FAQ records."""

from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FAQEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Public or disabled FAQ owned by one business and optionally one location."""

    __tablename__ = "faq_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_faq_entries_location_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_faq_entries_business_location", "business_id", "location_id"),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
