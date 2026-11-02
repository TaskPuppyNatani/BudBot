"""Optional isolated PostgreSQL proof of concurrent catalog category creation."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.catalog import CatalogCategory, CatalogProduct
from budbot.models.user import UserAccount
from budbot.schemas.catalog import ProductInput
from budbot.services.catalog_admin_service import CatalogAdminService


async def test_concurrent_owner_products_share_one_normalized_category():
    url = os.environ.get("BUDBOT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("BUDBOT_TEST_POSTGRES_URL is not configured")
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    bid, uid = uuid4(), uuid4()
    ready, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        async with factory.begin() as setup:
            setup.add_all([Business(id=bid, display_name="Isolated catalog test", industry="general_retail"),
                UserAccount(id=uid, email=f"catalog-{uid}@example.test", display_name="Catalog test")])

        async def save(name, category, first=False):
            async with factory() as session:
                if first:
                    commit = session.commit

                    async def hold_commit():
                        ready.set()
                        await release.wait()
                        await commit()

                    session.commit = hold_commit
                else:
                    scalar = session.scalar

                    async def observe_lock(statement, *args, **kwargs):
                        if getattr(statement, "_for_update_arg", None) is not None:
                            attempted.set()
                        return await scalar(statement, *args, **kwargs)

                    session.scalar = observe_lock
                return await CatalogAdminService(session, TenantContext(bid)).save_product(
                    ProductInput(name=name, category=category), uid)

        tasks.append(asyncio.create_task(save("First tea", "Drinks", first=True)))
        await asyncio.wait_for(ready.wait(), 5)
        tasks.append(asyncio.create_task(save("Second tea", "  DRINKS  ")))
        await asyncio.wait_for(attempted.wait(), 5)
        assert not tasks[1].done()
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        async with factory() as observer:
            assert await observer.scalar(select(func.count(CatalogCategory.id)).where(CatalogCategory.business_id == bid)) == 1
            assert await observer.scalar(select(func.count(CatalogProduct.id)).where(CatalogProduct.business_id == bid)) == 2
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with factory.begin() as cleanup:
            await cleanup.execute(delete(Business).where(Business.id == bid))
            await cleanup.execute(delete(UserAccount).where(UserAccount.id == uid))
        await engine.dispose()
