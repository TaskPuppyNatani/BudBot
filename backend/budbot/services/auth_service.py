"""Password login and opaque, revocable administrative session lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.config import Settings
from budbot.core.security import (
    new_opaque_token,
    password_hash_needs_rehash,
    rehash_password,
    secure_digest,
    token_digest,
    verify_password,
)
from budbot.core.time import ensure_utc, utc_now
from budbot.models.auth import AdminSession, LoginRateLimit
from budbot.models.user import UserAccount
from budbot.services.audit_service import record_audit_event

_DEVELOPMENT_RATE_LIMIT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class IssuedAdminSession:
    user: UserAccount
    record: AdminSession
    token: str
    csrf_token: str


def normalize_email(email: str) -> str:
    return email.strip().casefold()


class AuthService:
    """Authenticate accounts, throttle attempts, and issue new sessions."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.rate_limit_key = (
            settings.admin_login_rate_limit_key.get_secret_value()
            if settings.admin_login_rate_limit_key is not None
            else _DEVELOPMENT_RATE_LIMIT_KEY
        )

    async def _locked_buckets(
        self, email: str, peer_ip: str, now: datetime
    ) -> list[LoginRateLimit]:
        keys = [
            secure_digest(f"email:{normalize_email(email)}", self.rate_limit_key),
            secure_digest(f"ip:{peer_ip or 'unknown'}", self.rate_limit_key),
        ]
        retention = now - timedelta(
            seconds=max(
                self.settings.admin_login_window_seconds,
                self.settings.admin_login_lockout_seconds,
            )
            * 2
        )
        await self.session.execute(
            delete(LoginRateLimit).where(
                LoginRateLimit.window_started_at < retention,
                (LoginRateLimit.blocked_until.is_(None))
                | (LoginRateLimit.blocked_until <= now),
            )
        )
        dialect = self.session.get_bind().dialect.name
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        for key in keys:
            statement = insert(LoginRateLimit).values(
                key_digest=key,
                failed_attempts=0,
                window_started_at=now,
                blocked_until=None,
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=[LoginRateLimit.key_digest]
            )
            await self.session.execute(statement)
        rows = list(
            (
                await self.session.scalars(
                    select(LoginRateLimit)
                    .where(LoginRateLimit.key_digest.in_(keys))
                    .order_by(LoginRateLimit.key_digest)
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            if row.blocked_until and ensure_utc(row.blocked_until) > ensure_utc(now):
                continue
            if (
                ensure_utc(now) - ensure_utc(row.window_started_at)
            ).total_seconds() >= self.settings.admin_login_window_seconds:
                row.failed_attempts = 0
                row.window_started_at = now
                row.blocked_until = None
            elif row.blocked_until and ensure_utc(row.blocked_until) <= ensure_utc(now):
                row.failed_attempts = 0
                row.window_started_at = now
                row.blocked_until = None
        return rows

    async def authenticate(
        self, email: str, password: str, peer_ip: str
    ) -> IssuedAdminSession | None:
        now = utc_now()
        buckets = await self._locked_buckets(email, peer_ip, now)
        if any(
            bucket.blocked_until is not None
            and ensure_utc(bucket.blocked_until) > now
            for bucket in buckets
        ):
            # The failed attempts that caused the lockout are already audited.
            # Avoid turning each rejected retry into an unbounded audit-table write.
            return None

        normalized_email = normalize_email(email)
        user = await self.session.scalar(
            select(UserAccount).where(func.lower(UserAccount.email) == normalized_email)
        )
        valid_password = verify_password(
            user.password_hash if user is not None else None, password
        )
        if user is None or not user.active or not valid_password:
            newly_blocked = False
            for bucket in buckets:
                bucket.failed_attempts += 1
                if bucket.failed_attempts >= self.settings.admin_login_failure_limit:
                    bucket.blocked_until = now + timedelta(
                        seconds=self.settings.admin_login_lockout_seconds
                    )
                    newly_blocked = True
            await record_audit_event(
                self.session,
                "auth.login.failed",
                details={
                    "outcome": "locked" if newly_blocked else "failed",
                    "email_digest": secure_digest(
                        f"email:{normalized_email}", self.rate_limit_key
                    ),
                    "peer_digest": secure_digest(
                        f"ip:{peer_ip or 'unknown'}", self.rate_limit_key
                    ),
                },
            )
            return None

        for bucket in buckets:
            bucket.failed_attempts = 0
            bucket.window_started_at = now
            bucket.blocked_until = None

        if password_hash_needs_rehash(user.password_hash or ""):
            user.password_hash = rehash_password(password)

        token = new_opaque_token()
        csrf_token = new_opaque_token()
        admin_session = AdminSession(
            user_id=user.id,
            token_digest=token_digest(token),
            csrf_digest=token_digest(csrf_token),
            expires_at=now
            + timedelta(seconds=self.settings.admin_session_ttl_seconds),
        )
        self.session.add(admin_session)
        await record_audit_event(
            self.session,
            "auth.login.succeeded",
            actor_user_id=user.id,
            details={"outcome": "success"},
        )
        await self.session.flush()
        return IssuedAdminSession(
            user=user,
            record=admin_session,
            token=token,
            csrf_token=csrf_token,
        )

    async def revoke_session(self, session_id: UUID, user_id: UUID) -> bool:
        admin_session = await self.session.scalar(
            select(AdminSession).where(
                AdminSession.id == session_id,
                AdminSession.user_id == user_id,
                AdminSession.revoked_at.is_(None),
            )
        )
        if admin_session is None:
            return False
        admin_session.revoked_at = utc_now()
        await self.session.flush()
        return True

    async def revoke_all_sessions(self, user_id: UUID) -> int:
        now = utc_now()
        result = await self.session.execute(
            select(AdminSession)
            .where(
                AdminSession.user_id == user_id,
                AdminSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        active_sessions = list(result.scalars().all())
        for admin_session in active_sessions:
            admin_session.revoked_at = now
        await self.session.flush()
        return len(active_sessions)
