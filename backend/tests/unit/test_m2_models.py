"""M2 metadata, relationship, and constraint tests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.database.base import Base
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.user import BusinessMembership, UserAccount


def test_metadata_contains_only_m1_and_m2_tables() -> None:
    assert set(Base.metadata.tables) == {
        "assistant_configurations",
        "business_memberships",
        "businesses",
        "location_assistant_overrides",
        "location_hours",
        "locations",
        "user_accounts",
    }


async def test_user_can_hold_memberships_in_multiple_businesses(
    db_session: AsyncSession,
) -> None:
    user = UserAccount(email="owner@example.test", display_name="Owner")
    first = Business(display_name="First", industry="retail")
    second = Business(display_name="Second", industry="retail")
    first.assistant_configuration = AssistantConfiguration(
        display_name="First Helper", greeting="Hello", fallback_message="Try again"
    )
    second.assistant_configuration = AssistantConfiguration(
        display_name="Second Helper", greeting="Hi", fallback_message="Try again"
    )
    user.memberships = [
        BusinessMembership(business=first, role="owner"),
        BusinessMembership(business=second, role="admin"),
    ]
    db_session.add(user)
    await db_session.flush()

    memberships = list(
        (
            await db_session.scalars(
                select(BusinessMembership).where(
                    BusinessMembership.user_id == user.id
                )
            )
        ).all()
    )
    assert {membership.business_id for membership in memberships} == {
        first.id,
        second.id,
    }


async def test_one_business_can_own_multiple_locations(
    db_session: AsyncSession,
) -> None:
    business = Business(display_name="Multi", industry="retail")
    business.assistant_configuration = AssistantConfiguration(
        display_name="Helper", greeting="Hello", fallback_message="Try again"
    )
    business.locations = [
        Location(
            display_name="North",
            address_line_1="1 North St",
            city="Portland",
            region="OR",
            postal_code="97201",
            country="US",
            timezone="America/Los_Angeles",
        ),
        Location(
            display_name="South",
            address_line_1="2 South St",
            city="Portland",
            region="OR",
            postal_code="97202",
            country="US",
            timezone="America/Los_Angeles",
        ),
    ]
    db_session.add(business)
    await db_session.flush()

    assert len(business.locations) == 2
    assert {location.business_id for location in business.locations} == {business.id}
