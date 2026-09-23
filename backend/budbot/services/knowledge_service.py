"""Tenant-scoped public FAQ lookup with deterministic location overrides."""

from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.exceptions import CommandError
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.knowledge import FAQEntry


def normalize_faq_text(value: str) -> str:
    """Normalize case and whitespace for stable FAQ matching."""

    return " ".join(value.casefold().split())


class KnowledgeService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.entries = TenantScopedRepository(session, FAQEntry, tenant)

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
