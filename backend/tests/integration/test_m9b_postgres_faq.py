"""Optional PostgreSQL proof of concurrent normalized FAQ duplicate prevention.

Requires an isolated database migrated to Alembic head. No tables are created.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from budbot.core.exceptions import DomainError
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.knowledge import FAQEntry
from budbot.schemas.knowledge import FAQCreate
from budbot.services.knowledge_service import KnowledgeService


async def test_concurrent_public_faq_insert_has_one_winner():
    url = os.environ.get("BUDBOT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("BUDBOT_TEST_POSTGRES_URL is not configured")
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    bid = uuid4()
    ready, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        async with factory.begin() as setup:
            setup.add(Business(id=bid, display_name="Isolated FAQ test", industry="general_retail"))

        async def insert(question, first=False):
            async with factory.begin() as session:
                if not first:
                    scalar = session.scalar

                    async def observe_lock(statement, *args, **kwargs):
                        if getattr(statement, "_for_update_arg", None) is not None:
                            attempted.set()
                        return await scalar(statement, *args, **kwargs)

                    session.scalar = observe_lock
                entry = await KnowledgeService(session, TenantContext(bid)).create_admin_faq(
                    FAQCreate(question=question, answer="A test answer.")
                )
                if first:
                    ready.set()
                    await release.wait()
                return entry.id

        tasks.append(asyncio.create_task(insert("Parking?", first=True)))
        await asyncio.wait_for(ready.wait(), 5)
        tasks.append(asyncio.create_task(insert("  PARKING?  ")))
        await asyncio.wait_for(attempted.wait(), 5)
        assert not tasks[1].done()
        release.set()
        await asyncio.wait_for(tasks[0], 5)
        with pytest.raises(DomainError) as error:
            await asyncio.wait_for(tasks[1], 5)
        assert error.value.code == "FAQ_DUPLICATE"
        async with factory() as observer:
            assert await observer.scalar(select(func.count(FAQEntry.id)).where(FAQEntry.business_id == bid)) == 1
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with factory.begin() as cleanup:
            await cleanup.execute(delete(FAQEntry).where(FAQEntry.business_id == bid))
            await cleanup.execute(delete(Business).where(Business.id == bid))
        await engine.dispose()
