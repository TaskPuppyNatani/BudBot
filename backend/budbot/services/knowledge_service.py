"""Tenant-scoped FAQ management and deterministic public location overrides."""

from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.exceptions import CommandError, DomainError
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.knowledge import FAQEntry
from budbot.models.location import Location
from budbot.schemas.knowledge import FAQCreate, FAQUpdate
from budbot.services.business_service import BusinessService


def normalize_faq_text(value: str) -> str:
    """Normalize case and whitespace for stable FAQ matching."""

    return " ".join(value.casefold().split())


class KnowledgeService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.entries = TenantScopedRepository(session, FAQEntry, tenant)

    async def list_admin_faqs(self) -> tuple[FAQEntry, ...]:
        entries = list((await self.entries.session.scalars(self.entries.select())).all())
        return tuple(sorted(entries, key=lambda entry: (str(entry.location_id or ""), self._sort_key(entry))))

    async def _lock_admin_scope(self) -> None:
        # Serialize this tenant's FAQ writes, including inserts into an empty
        # scope. A row lock on FAQEntry alone cannot prevent duplicate inserts.
        await BusinessService(self.entries.session).get(
            self.entries.tenant, self.entries.tenant.business_id, for_update=True
        )

    async def _validate_admin_faq(self, entry: FAQEntry) -> None:
        if entry.location_id is not None:
            await TenantScopedRepository(
                self.entries.session, Location, self.entries.tenant
            ).get(entry.location_id, resource_name="location", for_update=True)
        if not entry.enabled or not entry.is_public:
            return
        statement = self.entries.select().where(
            FAQEntry.location_id == entry.location_id,
            FAQEntry.enabled.is_(True), FAQEntry.is_public.is_(True),
        )
        # Check before autoflush: a rejected edit must not publish partial state.
        with self.entries.session.no_autoflush:
            peers = (await self.entries.session.scalars(statement)).all()
        if any(peer.id != entry.id and normalize_faq_text(peer.question) == normalize_faq_text(entry.question) for peer in peers):
            raise DomainError(
                "An enabled public FAQ with this question already exists in this scope. Edit it or disable it first.",
                code="FAQ_DUPLICATE", status_code=409,
            )

    async def create_admin_faq(self, payload: FAQCreate) -> FAQEntry:
        await self._lock_admin_scope()
        entry = FAQEntry(business_id=self.entries.tenant.business_id, **payload.model_dump())
        await self._validate_admin_faq(entry)
        self.entries.session.add(entry)
        await self.entries.session.flush()
        await self.entries.session.refresh(entry)
        return entry

    async def update_admin_faq(self, entry_id: UUID, payload: FAQUpdate) -> FAQEntry:
        await self._lock_admin_scope()
        entry = await self.entries.get(entry_id, resource_name="FAQ", for_update=True)
        for name, value in payload.model_dump(exclude_unset=True).items():
            setattr(entry, name, value)
        with self.entries.session.no_autoflush:
            await self._validate_admin_faq(entry)
        await self.entries.session.flush()
        await self.entries.session.refresh(entry)
        return entry

    @staticmethod
    def _sort_key(entry: FAQEntry) -> tuple[str, str, str, str]:
        return (
            normalize_faq_text(entry.question),
            entry.question.casefold(),
            entry.question,
            str(entry.id),
        )

    async def public_faqs(self, location_id: UUID | None) -> tuple[FAQEntry, ...]:
        statement = self.entries.select().where(
            FAQEntry.enabled.is_(True), FAQEntry.is_public.is_(True)
        )
        if location_id is None:
            statement = statement.where(FAQEntry.location_id.is_(None))
        else:
            statement = statement.where(
                or_(
                    FAQEntry.location_id.is_(None),
                    FAQEntry.location_id == location_id,
                )
            )
        entries = list((await self.entries.session.scalars(statement)).all())
        entries.sort(key=self._sort_key)

        effective: dict[str, FAQEntry] = {}
        seen_scopes: set[tuple[UUID | None, str]] = set()
        for entry in entries:
            key = normalize_faq_text(entry.question)
            scope_key = (entry.location_id, key)
            if scope_key in seen_scopes:
                raise CommandError(
                    "FAQ_AMBIGUOUS",
                    "multiple public FAQs have the same question in one scope; "
                    "ask the business to resolve them",
                    status_code=409,
                )
            seen_scopes.add(scope_key)
            current = effective.get(key)
            if current is None or (
                location_id is not None
                and current.location_id is None
                and entry.location_id == location_id
            ):
                effective[key] = entry
        return tuple(sorted(effective.values(), key=self._sort_key))

    async def search_public_faqs(
        self, location_id: UUID | None, query: str
    ) -> tuple[FAQEntry, ...]:
        normalized_query = normalize_faq_text(query)
        entries = await self.public_faqs(location_id)
        exact = tuple(
            entry
            for entry in entries
            if normalize_faq_text(entry.question) == normalized_query
        )
        if exact:
            return exact
        return tuple(
            entry
            for entry in entries
            if normalized_query in normalize_faq_text(entry.question)
            or normalized_query in normalize_faq_text(entry.answer)
        )
