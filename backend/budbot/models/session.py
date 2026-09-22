"""Persistent, tenant-scoped customer sessions."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from budbot.compliance.age_gate import AgeGateStatus
from budbot.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from budbot.models.business import Business


_AGE_GATE_STATUS_SQL = ", ".join(
    f"'{status.value}'" for status in AgeGateStatus
)


class CustomerSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Opaque public session reference and its server-owned compliance state."""

    __tablename__ = "customer_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["selected_location_id", "business_id"],
            ["locations.id", "locations.business_id"],
            name="fk_customer_sessions_location_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"age_gate_status IN ({_AGE_GATE_STATUS_SQL})",
            name="ck_customer_sessions_age_gate_status",
        ),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    selected_location_id: Mapped[UUID | None] = mapped_column(
        Uuid, index=True
    )
    compliance_profile_id: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    compliance_profile_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    age_gate_status: Mapped[AgeGateStatus] = mapped_column(
        String(32),
        default=AgeGateStatus.NOT_REQUIRED.value,
        server_default=AgeGateStatus.NOT_REQUIRED.value,
        nullable=False,
    )
    age_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    business: Mapped["Business"] = relationship(back_populates="customer_sessions")

    @property
    def active_compliance_profile_id(self) -> str:
        """Compatibility/readability alias for the stored profile snapshot."""

        return self.compliance_profile_id

    @property
    def active_compliance_profile_version(self) -> str:
        """Compatibility/readability alias for the stored profile snapshot."""

        return self.compliance_profile_version
