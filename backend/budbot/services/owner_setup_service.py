"""Atomic, one-time initialization of the first administrative owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.exceptions import DomainError
from budbot.core.time import utc_now
from budbot.models.auth import AuthSetupState
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount
from budbot.schemas.assistant import AssistantCreate
from budbot.schemas.business import BusinessCreate
from budbot.services.audit_service import record_audit_event
from budbot.services.business_service import BusinessService


class OwnerSetupError(DomainError):
    status_code = 409
    code = "OWNER_SETUP_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OwnerSetupResult:
    user_id: UUID
    business_id: UUID
    business_name: str
    initialized_at: datetime


class OwnerSetupService:
    """Claim the singleton setup guard and attach one account to one business."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def initialize_first_owner(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        business_id: UUID | None,
        new_business_name: str | None = None,
    ) -> OwnerSetupResult:
        dialect = self.session.get_bind().dialect.name
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        seed_state = insert(AuthSetupState).values(
            id=1, initialized_at=None, owner_user_id=None
        )
        await self.session.execute(
            seed_state.on_conflict_do_nothing(index_elements=[AuthSetupState.id])
        )
        now = utc_now()
        reservation = await self.session.execute(
            update(AuthSetupState)
            .where(
                AuthSetupState.id == 1,
                AuthSetupState.initialized_at.is_(None),
            )
            .values(initialized_at=now)
        )
        if reservation.rowcount != 1:
            raise OwnerSetupError(
                "The first owner has already been initialized. Ask an existing "
                "owner to add accounts through the authenticated administration workflow."
            )

        normalized_email = email.strip().casefold()
        matches = list(
            (
                await self.session.scalars(
                    select(UserAccount)
                    .where(func.lower(UserAccount.email) == normalized_email)
                    .with_for_update()
                )
            ).all()
        )
        if len(matches) > 1:
            raise OwnerSetupError(
                "Multiple legacy accounts use this email with different casing. "
                "Resolve the duplicate accounts before owner setup."
            )
        user = matches[0] if matches else None
        if user is not None:
            if user.password_hash is not None:
                raise OwnerSetupError(
                    "This account already has credentials. Choose an unused email "
                    "or use the account's authenticated recovery workflow."
                )
            if not user.active:
                raise OwnerSetupError(
                    "This legacy account is inactive. Choose an active owner account."
                )
            other_memberships = list(
                (
                    await self.session.scalars(
                        select(BusinessMembership).where(
                            BusinessMembership.user_id == user.id,
                            BusinessMembership.business_id != business_id,
                        )
                    )
                ).all()
            )
            if other_memberships:
                raise OwnerSetupError(
                    "This legacy account already has memberships in other businesses. "
                    "Use a new owner email so setup does not activate unselected tenants."
                )
            user.display_name = display_name.strip()
            user.password_hash = password_hash
        else:
            user = UserAccount(
                email=normalized_email,
                display_name=display_name.strip(),
                password_hash=password_hash,
                active=True,
            )
            self.session.add(user)
            await self.session.flush()

        if business_id is None:
            existing_business = await self.session.scalar(
                select(Business.id).limit(1)
            )
            if existing_business is not None:
                raise OwnerSetupError(
                    "An existing business is present, so setup cannot create a new "
                    "first tenant. Select an active business explicitly."
                )
            name = (new_business_name or "").strip()
            if not name:
                raise OwnerSetupError(
                    "No active business exists. Supply a name for the first business."
                )
            business = await BusinessService(self.session).create(
                BusinessCreate(
                    display_name=name,
                    industry="general_retail",
                    default_timezone="UTC",
                    assistant=AssistantCreate(
                        display_name=f"{name} Assistant",
                        greeting=f"Welcome to {name}.",
                        fallback_message="Please ask a team member for help.",
                    ),
                )
            )
        else:
            business = await self.session.scalar(
                select(Business).where(
                    Business.id == business_id,
                    Business.active.is_(True),
                )
            )
            if business is None:
                raise OwnerSetupError(
                    "The selected business is unavailable or inactive; no setup changes were kept."
                )

        membership = await self.session.scalar(
            select(BusinessMembership).where(
                BusinessMembership.user_id == user.id,
                BusinessMembership.business_id == business.id,
            )
        )
        if membership is None:
            self.session.add(
                BusinessMembership(
                    user_id=user.id,
                    business_id=business.id,
                    role="owner",
                )
            )
        else:
            membership.role = "owner"

        state = await self.session.get(AuthSetupState, 1)
        assert state is not None
        state.owner_user_id = user.id
        await record_audit_event(
            self.session,
            "auth.owner_setup.completed",
            actor_user_id=user.id,
            business_id=business.id,
            resource_type="business",
            resource_id=business.id,
            details={"method": "local_cli"},
        )
        await self.session.flush()
        return OwnerSetupResult(
            user_id=user.id,
            business_id=business.id,
            business_name=business.display_name,
            initialized_at=now,
        )
