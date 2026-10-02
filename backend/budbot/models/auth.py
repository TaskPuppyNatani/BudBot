"""Persistent state for administrative sessions and bounded login throttling."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from budbot.database.base import Base, UUIDPrimaryKeyMixin


class AdminSession(UUIDPrimaryKeyMixin, Base):
    """A revocable server-side session; only token digests are stored."""

    __tablename__ = "admin_sessions"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_admin_sessions_token_digest"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSetupState(Base):
    """Singleton guard that makes first-owner setup a one-time DB operation."""

    __tablename__ = "auth_setup_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_auth_setup_state_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )


class LoginRateLimit(Base):
    """Hashed independent identifier/IP buckets for repeated login attempts."""

    __tablename__ = "admin_login_rate_limits"

    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only authentication and administrative activity record."""

    __tablename__ = "audit_events"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), index=True
    )
    business_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
