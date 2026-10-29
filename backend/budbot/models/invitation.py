"""Tenant-scoped, single-use invitations to join a business."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from budbot.database.base import Base, UUIDPrimaryKeyMixin


class BusinessInvitation(UUIDPrimaryKeyMixin, Base):
    """An invitation stores a token digest and immutable access intent only."""

    __tablename__ = "business_invitations"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_business_invitations_token_digest"),
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("user_accounts.id", ondelete="SET NULL"), index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
