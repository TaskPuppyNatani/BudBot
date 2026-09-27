"""Create or locate the non-destructive local preview business."""

import asyncio
from uuid import UUID

from sqlalchemy import or_, select, text

from budbot.core.config import get_settings
from budbot.core.tenancy import TenantContext
from budbot.database.session import Database
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.assistant import AssistantCreate
from budbot.schemas.business import BusinessCreate
from budbot.schemas.location import LocationCreate
from budbot.services.business_service import BusinessService
from budbot.services.location_service import LocationService

DEMO_NAME = "BudBot Local Demo"
DEMO_LEGAL_NAME = "BudBot local launcher managed demo"
DEMO_WEBSITE = "https://budbot.local.invalid"
DEMO_LOCATION_MARKER = "budbot-local-preview-v1"
DEMO_LOCATION_NAME = "BudBot Preview Location"
_LOCK_KEY = 7_321_854_900_126


async def ensure_demo() -> UUID:
    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            async with session.begin():
                # Prevent concurrent launcher clicks from creating duplicate seeds.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY}
                )
                marked = list(
                    (
                        await session.scalars(
                            select(Business)
                            .where(
                                or_(
                                    Business.legal_name == DEMO_LEGAL_NAME,
                                    Business.website_url == DEMO_WEBSITE,
                                )
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                if len(marked) > 1:
                    raise RuntimeError("multiple launcher demo businesses were found")
                business = marked[0] if marked else None

                if business is None:
                    name_conflict = await session.scalar(
                        select(Business.id).where(Business.display_name == DEMO_NAME)
                    )
                    if name_conflict is not None:
                        raise RuntimeError(
                            "a business named 'BudBot Local Demo' already exists but "
                            "is not marked as launcher-managed; no data was changed"
                        )
                    business = await BusinessService(session).create(
                        BusinessCreate(
                            display_name=DEMO_NAME,
                            legal_name=DEMO_LEGAL_NAME,
                            website_url=DEMO_WEBSITE,
                            industry="general_retail",
                            primary_brand_color="#2563EB",
                            default_timezone="America/Los_Angeles",
                            assistant=AssistantCreate(
                                display_name="BudBot Assistant",
                                greeting="Hi! Ask me about this store, or try /help.",
                                fallback_message=(
                                    "I can help with store information and commands. "
                                    "Try /help to see what is available."
                                ),
                            ),
                        )
                    )

                if not business.active:
                    raise RuntimeError(
                        "the launcher demo business is inactive; it was left unchanged"
                    )

                active_location = await session.scalar(
                    select(Location)
                    .where(
                        Location.business_id == business.id,
                        Location.active.is_(True),
                    )
                    .order_by(Location.created_at, Location.id)
                    .limit(1)
                )
                if active_location is None:
                    marked_location = await session.scalar(
                        select(Location)
                        .where(
                            Location.business_id == business.id,
                            Location.maps_place_id == DEMO_LOCATION_MARKER,
                        )
                        .with_for_update()
                    )
                    if marked_location is not None:
                        raise RuntimeError(
                            "the launcher demo location is inactive; it was left "
                            "unchanged. Reactivate it through your own data-management "
                            "workflow or select another active location."
                        )
                    await LocationService(
                        session, TenantContext(business.id)
                    ).create(
                        business.id,
                        LocationCreate(
                            display_name=DEMO_LOCATION_NAME,
                            address_line_1="100 Demo Street",
                            city="Portland",
                            region="Oregon",
                            region_code="OR",
                            postal_code="97201",
                            country="US",
                            timezone="America/Los_Angeles",
                            active=True,
                            maps_place_id=DEMO_LOCATION_MARKER,
                        ),
                    )
                business_id = business.id
            return business_id
    finally:
        await database.dispose()


def main() -> None:
    try:
        print(asyncio.run(ensure_demo()))
    except Exception as exc:
        print(f"Demo setup failed: {exc}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
