"""Tenant-scoped team and invitation operations with serialized owner checks."""

from __future__ import annotations

from datetime import timedelta
import hmac
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.config import Settings
from budbot.core.exceptions import DomainError
from budbot.core.permissions import AdminPermission, ROLE_PERMISSIONS, role_allows
from budbot.core.security import (
    hash_password,
    new_opaque_token,
    secure_digest,
    token_digest,
    validate_new_password,
)
from budbot.core.tenancy import TenantContext
from budbot.core.time import ensure_utc, utc_now
from budbot.models.auth import AdminSession, LoginRateLimit
from budbot.models.business import Business
from budbot.models.invitation import BusinessInvitation
from budbot.models.user import BusinessMembership, UserAccount
from budbot.schemas.team import InvitationPreview, MemberRead, PendingInvitationRead
from budbot.services.audit_service import record_audit_event
from budbot.services.business_service import BusinessService

_DEV_RATE_KEY = secrets.token_bytes(32)
_PUBLIC_ATTEMPT_LIMIT = 30
_PUBLIC_WINDOW_SECONDS = 60


class TeamError(DomainError):
    """Safe team-workflow errors for owner-facing responses."""


def normalize_email(value: str) -> str:
    return value.strip().casefold()


class TeamService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def list_team(self, business_id: UUID) -> dict[str, list[object]]:
        now = utc_now()
        members = list((await self.session.execute(
            select(BusinessMembership, UserAccount)
            .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
            .where(BusinessMembership.business_id == business_id)
            .order_by(func.lower(UserAccount.display_name), func.lower(UserAccount.email))
        )).all())
        invitations = list((await self.session.scalars(
            select(BusinessInvitation)
            .where(
                BusinessInvitation.business_id == business_id,
                BusinessInvitation.accepted_at.is_(None),
                BusinessInvitation.revoked_at.is_(None),
                BusinessInvitation.expires_at > now,
            )
            .order_by(BusinessInvitation.created_at.desc())
        )).all())
        return {
            "members": [MemberRead(
                membership_id=membership.id,
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=membership.role,
                active=user.active,
                created_at=membership.created_at,
            ) for membership, user in members],
            "invitations": [PendingInvitationRead(
                invitation_id=invite.id,
                email=invite.recipient_email,
                role=invite.role,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
            ) for invite in invitations],
        }

    async def _lock_business_and_authorize(self, business_id: UUID, actor_id: UUID) -> Business:
        business = await BusinessService(self.session).get(
            TenantContext(business_id=business_id), business_id, for_update=True
        )
        if not business.active:
            raise TeamError("This business is unavailable.", status_code=404)
        row = (await self.session.execute(
            select(UserAccount, BusinessMembership)
            .join(BusinessMembership, BusinessMembership.user_id == UserAccount.id)
            .where(
                UserAccount.id == actor_id,
                BusinessMembership.business_id == business_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )).first()
        if row is None or not row[0].active or not role_allows(
            row[1].role, AdminPermission.MEMBERSHIP_MANAGE
        ):
            raise TeamError("Only an active business owner can manage this team.", status_code=403)
        return business

    async def _active_owner_count(self, business_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(BusinessMembership)
            .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
            .where(
                BusinessMembership.business_id == business_id,
                BusinessMembership.role == "owner",
                UserAccount.active.is_(True),
            )
        )
        return int(count or 0)

    async def _revoke_invitations(
        self, business_id: UUID, actor_id: UUID, now, *,
        created_by_user_id: UUID | None = None,
        recipient_email: str | None = None,
    ) -> None:
        statement = select(BusinessInvitation).where(
            BusinessInvitation.business_id == business_id,
            BusinessInvitation.accepted_at.is_(None),
            BusinessInvitation.revoked_at.is_(None),
        )
        if created_by_user_id is not None:
            statement = statement.where(BusinessInvitation.created_by_user_id == created_by_user_id)
        if recipient_email is not None:
            statement = statement.where(BusinessInvitation.recipient_email == recipient_email)
        invitations = list((await self.session.scalars(
            statement.with_for_update().execution_options(populate_existing=True)
        )).all())
        for invitation in invitations:
            invitation.revoked_at = now
            await record_audit_event(
                self.session, "admin.membership.invitation_revoked", actor_user_id=actor_id,
                business_id=business_id, resource_type="business_invitation",
                resource_id=invitation.id,
            )

    async def create_invitation(
        self, business_id: UUID, actor_id: UUID, email: str, role: str,
    ) -> tuple[BusinessInvitation, str]:
        await self._lock_business_and_authorize(business_id, actor_id)
        normalized = normalize_email(email)
        if "@" not in normalized or any(char.isspace() for char in normalized):
            raise TeamError("Enter a valid email address.", status_code=422)
        if role not in ROLE_PERMISSIONS:
            raise TeamError("Choose a valid team role.", status_code=422)
        now = utc_now()
        duplicate_member = await self.session.scalar(
            select(BusinessMembership.id)
            .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
            .where(
                BusinessMembership.business_id == business_id,
                func.lower(UserAccount.email) == normalized,
                UserAccount.active.is_(True),
            )
        )
        if duplicate_member:
            raise TeamError("This person already belongs to this business.", status_code=409)
        pending = await self.session.scalar(
            select(BusinessInvitation.id).where(
                BusinessInvitation.business_id == business_id,
                BusinessInvitation.recipient_email == normalized,
                BusinessInvitation.accepted_at.is_(None),
                BusinessInvitation.revoked_at.is_(None),
                BusinessInvitation.expires_at > now,
            )
        )
        if pending:
            raise TeamError("An invitation for this person is already waiting.", status_code=409)
        token = new_opaque_token()
        invitation = BusinessInvitation(
            business_id=business_id,
            recipient_email=normalized,
            role=role,
            created_by_user_id=actor_id,
            token_digest=token_digest(token),
            expires_at=now + timedelta(seconds=(self.settings.admin_invitation_ttl_seconds if self.settings else 604_800)),
        )
        self.session.add(invitation)
        await self.session.flush()
        await record_audit_event(
            self.session, "admin.membership.invited", actor_user_id=actor_id,
            business_id=business_id, resource_type="business_invitation",
            resource_id=invitation.id, details={"role": role},
        )
        return invitation, token

    async def revoke_invitation(self, business_id: UUID, actor_id: UUID, invitation_id: UUID) -> None:
        await self._lock_business_and_authorize(business_id, actor_id)
        invite = await self.session.scalar(
            select(BusinessInvitation).where(
                BusinessInvitation.id == invitation_id,
                BusinessInvitation.business_id == business_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        now = utc_now()
        if invite is None or invite.accepted_at is not None or invite.revoked_at is not None:
            raise TeamError("This invitation is no longer available.", status_code=404)
        invite.revoked_at = now
        await record_audit_event(
            self.session, "admin.membership.invitation_revoked", actor_user_id=actor_id,
            business_id=business_id, resource_type="business_invitation",
            resource_id=invite.id,
        )

    async def change_role(
        self, business_id: UUID, actor_id: UUID, membership_id: UUID, role: str,
    ) -> None:
        await self._lock_business_and_authorize(business_id, actor_id)
        if role not in ROLE_PERMISSIONS:
            raise TeamError("Choose a valid team role.", status_code=422)
        row = (await self.session.execute(
            select(BusinessMembership, UserAccount)
            .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
            .where(
                BusinessMembership.id == membership_id,
                BusinessMembership.business_id == business_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )).first()
        if row is None:
            raise TeamError("This team member is no longer available.", status_code=404)
        membership, user = row
        previous = membership.role
        if previous == "owner" and role != "owner" and user.active:
            if await self._active_owner_count(business_id) <= 1:
                raise TeamError("You’re the only owner of this business. Add another owner before changing or removing your access.", status_code=409)
        membership.role = role
        if previous == "owner" and role != "owner":
            await self._revoke_invitations(
                business_id, actor_id, utc_now(), created_by_user_id=user.id
            )
        await record_audit_event(
            self.session, "admin.membership.role_changed", actor_user_id=actor_id,
            business_id=business_id, resource_type="business_membership",
            resource_id=membership.id, details={"role": role},
        )

    async def remove_member(self, business_id: UUID, actor_id: UUID, membership_id: UUID) -> None:
        await self._lock_business_and_authorize(business_id, actor_id)
        row = (await self.session.execute(
            select(BusinessMembership, UserAccount)
            .join(UserAccount, UserAccount.id == BusinessMembership.user_id)
            .where(
                BusinessMembership.id == membership_id,
                BusinessMembership.business_id == business_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )).first()
        if row is None:
            raise TeamError("This team member is no longer available.", status_code=404)
        membership, user = row
        if membership.role == "owner" and user.active and await self._active_owner_count(business_id) <= 1:
            raise TeamError("You’re the only owner of this business. Add another owner before changing or removing your access.", status_code=409)
        await self._revoke_invitations(
            business_id, actor_id, utc_now(), created_by_user_id=user.id
        )
        await self._revoke_invitations(
            business_id, actor_id, utc_now(), recipient_email=normalize_email(user.email)
        )
        await record_audit_event(
            self.session, "admin.membership.removed", actor_user_id=actor_id,
            business_id=business_id, resource_type="business_membership",
            resource_id=membership.id,
        )
        await self.session.delete(membership)

    async def _find_invitation(self, token: str, *, lock: bool) -> tuple[BusinessInvitation, Business]:
        digest = token_digest(token)
        invitation_id = await self.session.scalar(
            select(BusinessInvitation.id).where(BusinessInvitation.token_digest == digest)
        )
        if invitation_id is None:
            raise TeamError("This invitation can’t be used. Ask the business owner for a new link.", status_code=404)
        initial = await self.session.get(BusinessInvitation, invitation_id)
        if initial is None:
            raise TeamError("This invitation can’t be used. Ask the business owner for a new link.", status_code=404)
        business = await BusinessService(self.session).get(
            TenantContext(business_id=initial.business_id), initial.business_id, for_update=lock
        )
        statement = select(BusinessInvitation).where(
            BusinessInvitation.id == invitation_id,
            BusinessInvitation.token_digest == digest,
            BusinessInvitation.business_id == business.id,
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        invitation = await self.session.scalar(statement)
        now = utc_now()
        if (
            not business.active or invitation is None or invitation.accepted_at is not None
            or invitation.revoked_at is not None or ensure_utc(invitation.expires_at) <= ensure_utc(now)
        ):
            raise TeamError("This invitation can’t be used. Ask the business owner for a new link.", status_code=404)
        return invitation, business

    async def inspect_invitation(self, token: str) -> InvitationPreview:
        invitation, business = await self._find_invitation(token, lock=False)
        return InvitationPreview(
            email=invitation.recipient_email,
            business_name=business.display_name,
            role=invitation.role,
            expires_at=invitation.expires_at,
        )

    async def check_public_attempt_limit(self, peer_ip: str) -> None:
        await self._rate_limit_public_attempt(peer_ip)

    async def _rate_limit_public_attempt(self, peer_ip: str) -> None:
        if self.settings is None:
            return
        key = self.settings.admin_login_rate_limit_key.get_secret_value() if self.settings.admin_login_rate_limit_key else _DEV_RATE_KEY
        digest = secure_digest(f"invitation-ip:{peer_ip or 'unknown'}", key)
        now = utc_now()
        dialect = self.session.get_bind().dialect.name
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        seed = insert(LoginRateLimit).values(
            key_digest=digest, failed_attempts=0, window_started_at=now, blocked_until=None
        ).on_conflict_do_nothing(index_elements=[LoginRateLimit.key_digest])
        await self.session.execute(seed)
        bucket = await self.session.scalar(
            select(LoginRateLimit).where(LoginRateLimit.key_digest == digest)
            .with_for_update().execution_options(populate_existing=True)
        )
        if bucket is None:
            return
        if bucket.blocked_until and ensure_utc(bucket.blocked_until) > ensure_utc(now):
            raise TeamError("Too many attempts. Wait a minute and try again.", status_code=429)
        if (ensure_utc(now) - ensure_utc(bucket.window_started_at)).total_seconds() >= _PUBLIC_WINDOW_SECONDS:
            bucket.failed_attempts = 0
            bucket.window_started_at = now
            bucket.blocked_until = None
        bucket.failed_attempts += 1
        newly_blocked = False
        if bucket.failed_attempts > _PUBLIC_ATTEMPT_LIMIT:
            bucket.blocked_until = now + timedelta(seconds=_PUBLIC_WINDOW_SECONDS)
            newly_blocked = True
        # Token inspection/acceptance errors roll back the request transaction.
        # Persist the IP bucket before validating the bearer token so invalid,
        # expired, and revoked-token probes are still counted.
        await self.session.commit()
        if newly_blocked:
            raise TeamError("Too many attempts. Wait a minute and try again.", status_code=429)

    async def accept_new_account(
        self, token: str, display_name: str, password: str, peer_ip: str,
    ) -> None:
        await self._rate_limit_public_attempt(peer_ip)
        invitation, business = await self._find_invitation(token, lock=True)
        display_name = display_name.strip()
        if not display_name:
            raise TeamError("Enter your name to finish joining the business.", status_code=422)
        try:
            validate_new_password(password)
            password_hash = hash_password(password)
        except ValueError as exc:
            raise TeamError(str(exc), status_code=422) from None
        matches = list((await self.session.scalars(
            select(UserAccount).where(func.lower(UserAccount.email) == invitation.recipient_email)
        )).all())
        matches = [user for user in matches if normalize_email(user.email) == invitation.recipient_email]
        if len(matches) > 1:
            raise TeamError("This invitation can’t be activated. Ask the business owner for help.", status_code=409)
        if matches:
            user = matches[0]
            if user.active and user.password_hash:
                raise TeamError("This invitation is for an existing account. Sign in as that person to accept it.", status_code=409)
            raise TeamError("This account can’t accept the invitation here. Ask the business owner for help.", status_code=409)
        user = UserAccount(
            email=invitation.recipient_email,
            display_name=display_name.strip(),
            password_hash=password_hash,
            active=True,
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError:
            raise TeamError("This invitation can’t be activated right now. Sign in if you already have an account, then accept the invitation.", status_code=409) from None
        invitation.accepted_at = utc_now()
        self.session.add(BusinessMembership(
            user_id=user.id, business_id=business.id, role=invitation.role,
        ))
        await record_audit_event(
            self.session, "admin.membership.invitation_accepted", actor_user_id=user.id,
            business_id=business.id, resource_type="business_invitation",
            resource_id=invitation.id, details={"role": invitation.role},
        )
        await self.session.flush()

    async def accept_existing_account(
        self, token: str, user_id: UUID, session_id: UUID, csrf_candidate: str,
        peer_ip: str,
    ) -> None:
        await self._rate_limit_public_attempt(peer_ip)
        invitation, business = await self._find_invitation(token, lock=True)
        session_record = await self.session.scalar(
            select(AdminSession).where(
                AdminSession.id == session_id, AdminSession.user_id == user_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        user = await self.session.scalar(
            select(UserAccount).where(UserAccount.id == user_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        now = utc_now()
        if (
            session_record is None or session_record.revoked_at is not None
            or ensure_utc(session_record.expires_at) <= ensure_utc(now)
            or not hmac.compare_digest(token_digest(csrf_candidate), session_record.csrf_digest)
            or user is None or not user.active or normalize_email(user.email) != invitation.recipient_email
        ):
            raise TeamError("Sign in with the account invited to this business, then try again.", status_code=403)
        existing = await self.session.scalar(
            select(BusinessMembership.id).where(
                BusinessMembership.user_id == user.id,
                BusinessMembership.business_id == business.id,
            )
        )
        if existing:
            raise TeamError("This account already belongs to the business.", status_code=409)
        invitation.accepted_at = now
        self.session.add(BusinessMembership(
            user_id=user.id, business_id=business.id, role=invitation.role,
        ))
        await record_audit_event(
            self.session, "admin.membership.invitation_accepted", actor_user_id=user.id,
            business_id=business.id, resource_type="business_invitation",
            resource_id=invitation.id, details={"role": invitation.role},
        )
        await self.session.flush()
