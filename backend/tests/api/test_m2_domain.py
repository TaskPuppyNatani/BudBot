"""End-to-end M2 API, isolation, and inheritance tests."""

from copy import deepcopy
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.models.location import LocationHours


def business_payload(name: str, assistant_name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "industry": "general_retail",
        "default_timezone": "America/Los_Angeles",
        "assistant": {
            "display_name": assistant_name,
            "greeting": f"Welcome to {name}",
            "fallback_message": "Please ask a team member.",
            "enabled": True,
        },
    }


def location_payload(name: str, address: str) -> dict[str, object]:
    return {
        "display_name": name,
        "address_line_1": address,
        "city": "Portland",
        "region": "OR",
        "postal_code": "97201",
        "country": "us",
        "phone": "+1 (503) 555-0100",
        "timezone": "America/Los_Angeles",
        "hours": [
            {
                "day_of_week": 0,
                "open_time": "09:00:00",
                "close_time": "17:00:00",
                "is_closed": False,
            },
            {"day_of_week": 1, "is_closed": True},
        ],
    }


def tenant_header(business_id: str) -> dict[str, str]:
    return {"X-BudBot-Business-ID": business_id}


async def create_business(
    client: AsyncClient, name: str, assistant_name: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/businesses", json=business_payload(name, assistant_name)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_location(
    client: AsyncClient,
    business_id: str,
    name: str,
    address: str,
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=tenant_header(business_id),
        json=location_payload(name, address),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_business_creation_update_and_assistant_rename_are_stable(
    m2_client: AsyncClient,
) -> None:
    business = await create_business(m2_client, "Green Shop", "Leaf")
    business_id = business["id"]
    UUID(str(business_id))

    assistant_before = await m2_client.get(
        f"/api/v1/businesses/{business_id}/assistant",
        headers=tenant_header(str(business_id)),
    )
    assert assistant_before.status_code == 200
    assistant_id = assistant_before.json()["id"]
    assert assistant_before.json()["display_name"] == "Leaf"

    renamed = await m2_client.patch(
        f"/api/v1/businesses/{business_id}/assistant",
        headers=tenant_header(str(business_id)),
        json={"display_name": "Poppy"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["id"] == assistant_id
    assert renamed.json()["display_name"] == "Poppy"
    assert "BudBot" not in renamed.text

    updated = await m2_client.patch(
        f"/api/v1/businesses/{business_id}",
        headers=tenant_header(str(business_id)),
        json={"display_name": "Green Shop Cooperative"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == business_id


async def test_multi_location_hours_inactive_behavior_and_scoped_listing(
    m2_client: AsyncClient,
) -> None:
    first_business = await create_business(m2_client, "First", "First Helper")
    second_business = await create_business(m2_client, "Second", "Second Helper")
    first_id, second_id = str(first_business["id"]), str(second_business["id"])
    north = await create_location(m2_client, first_id, "North", "1 North St")
    south_payload = location_payload("South", "2 South St")
    south_payload["timezone"] = "America/Denver"
    south_payload["hours"] = [
        {
            "day_of_week": 0,
            "open_time": "10:00:00",
            "close_time": "18:00:00",
            "is_closed": False,
        }
    ]
    south_response = await m2_client.post(
        f"/api/v1/businesses/{first_id}/locations",
        headers=tenant_header(first_id),
        json=south_payload,
    )
    assert south_response.status_code == 201
    south = south_response.json()
    await create_location(m2_client, second_id, "Other Tenant", "3 Other St")

    assert north["address_line_1"] != south["address_line_1"]
    assert north["timezone"] != south["timezone"]
    assert north["hours"] != south["hours"]
    assert north["hours"][1]["is_closed"] is True

    deactivated = await m2_client.post(
        f"/api/v1/businesses/{first_id}/locations/{south['id']}/deactivate",
        headers=tenant_header(first_id),
    )
    assert deactivated.status_code == 200
    active_list = await m2_client.get(
        f"/api/v1/businesses/{first_id}/locations",
        headers=tenant_header(first_id),
    )
    assert [item["id"] for item in active_list.json()] == [north["id"]]
    all_locations = await m2_client.get(
        f"/api/v1/businesses/{first_id}/locations?include_inactive=true",
        headers=tenant_header(first_id),
    )
    assert {item["id"] for item in all_locations.json()} == {
        north["id"],
        south["id"],
    }


async def test_location_hours_update_replaces_existing_weekday_without_duplicates(
    m2_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    business = await create_business(m2_client, "Hours", "Hours Helper")
    business_id = str(business["id"])
    location = await create_location(m2_client, business_id, "Main", "1 Main St")

    updated = await m2_client.patch(
        f"/api/v1/businesses/{business_id}/locations/{location['id']}",
        headers=tenant_header(business_id),
        json={
            "hours": [
                {
                    "day_of_week": 0,
                    "open_time": "10:00:00",
                    "close_time": "18:00:00",
                    "is_closed": False,
                },
                {"day_of_week": 1, "is_closed": True},
            ]
        },
    )

    assert updated.status_code == 200, updated.text
    monday_rows = [row for row in updated.json()["hours"] if row["day_of_week"] == 0]
    assert len(monday_rows) == 1
    assert monday_rows[0]["open_time"] == "10:00:00"
    assert monday_rows[0]["close_time"] == "18:00:00"
    assert [row["day_of_week"] for row in updated.json()["hours"]] == [0, 1]
    stored_mondays = list(
        (
            await db_session.scalars(
                select(LocationHours).where(
                    LocationHours.location_id == UUID(str(location["id"])),
                    LocationHours.day_of_week == 0,
                )
            )
        ).all()
    )
    assert len(stored_mondays) == 1


async def test_tenant_isolation_blocks_reads_updates_lists_and_resolution(
    m2_client: AsyncClient,
) -> None:
    tenant_a = await create_business(m2_client, "Tenant A", "A Helper")
    tenant_b = await create_business(m2_client, "Tenant B", "B Helper")
    a_id, b_id = str(tenant_a["id"]), str(tenant_b["id"])
    a_location = await create_location(m2_client, a_id, "A Location", "1 A St")
    b_location = await create_location(m2_client, b_id, "B Location", "1 B St")

    cross_read = await m2_client.get(
        f"/api/v1/businesses/{a_id}/locations/{b_location['id']}",
        headers=tenant_header(a_id),
    )
    assert cross_read.status_code == 404
    cross_update = await m2_client.patch(
        f"/api/v1/businesses/{a_id}/locations/{b_location['id']}",
        headers=tenant_header(a_id),
        json={"display_name": "Stolen"},
    )
    assert cross_update.status_code == 404
    cross_assistant = await m2_client.get(
        f"/api/v1/businesses/{b_id}/assistant",
        headers=tenant_header(a_id),
    )
    assert cross_assistant.status_code == 404
    cross_effective = await m2_client.get(
        f"/api/v1/businesses/{a_id}/locations/{b_location['id']}/effective-assistant",
        headers=tenant_header(a_id),
    )
    assert cross_effective.status_code == 404

    scoped_list = await m2_client.get(
        f"/api/v1/businesses/{a_id}/locations", headers=tenant_header(a_id)
    )
    assert [item["id"] for item in scoped_list.json()] == [a_location["id"]]

    cross_deactivate = await m2_client.post(
        f"/api/v1/businesses/{a_id}/locations/{b_location['id']}/deactivate",
        headers=tenant_header(a_id),
    )
    assert cross_deactivate.status_code == 404
    cross_override = await m2_client.patch(
        f"/api/v1/businesses/{a_id}/locations/{b_location['id']}/assistant-override",
        headers=tenant_header(a_id),
        json={"display_name": "Stolen"},
    )
    assert cross_override.status_code == 404


async def test_override_inherit_override_and_clear_for_two_locations(
    m2_client: AsyncClient,
) -> None:
    business = await create_business(m2_client, "Overrides", "Store Helper")
    business_id = str(business["id"])
    first = await create_location(m2_client, business_id, "First", "1 First St")
    second = await create_location(m2_client, business_id, "Second", "2 Second St")
    assistant = await m2_client.get(
        f"/api/v1/businesses/{business_id}/assistant",
        headers=tenant_header(business_id),
    )
    assistant_id = assistant.json()["id"]

    first_effective = await m2_client.get(
        f"/api/v1/businesses/{business_id}/locations/{first['id']}/effective-assistant",
        headers=tenant_header(business_id),
    )
    assert first_effective.json()["display_name"] == "Store Helper"

    override = await m2_client.patch(
        f"/api/v1/businesses/{business_id}/locations/{first['id']}/assistant-override",
        headers=tenant_header(business_id),
        json={
            "display_name": "First Guide",
            "greeting": "Hello First",
            "enabled": False,
        },
    )
    assert override.status_code == 200
    first_overridden = await m2_client.get(
        f"/api/v1/businesses/{business_id}/locations/{first['id']}/effective-assistant",
        headers=tenant_header(business_id),
    )
    second_effective = await m2_client.get(
        f"/api/v1/businesses/{business_id}/locations/{second['id']}/effective-assistant",
        headers=tenant_header(business_id),
    )
    assert first_overridden.json()["display_name"] == "First Guide"
    assert first_overridden.json()["enabled"] is False
    assert first_overridden.json()["assistant_id"] == assistant_id
    assert second_effective.json()["display_name"] == "Store Helper"
    assert second_effective.json()["enabled"] is True

    cleared = await m2_client.patch(
        f"/api/v1/businesses/{business_id}/locations/{first['id']}/assistant-override",
        headers=tenant_header(business_id),
        json={"display_name": None, "greeting": None, "enabled": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["id"] == override.json()["id"]
    inherited_again = await m2_client.get(
        f"/api/v1/businesses/{business_id}/locations/{first['id']}/effective-assistant",
        headers=tenant_header(business_id),
    )
    assert inherited_again.json()["display_name"] == "Store Helper"
    assert inherited_again.json()["enabled"] is True


async def test_invalid_hours_timezone_url_and_duplicate_days_are_rejected(
    m2_client: AsyncClient,
) -> None:
    invalid_business = deepcopy(business_payload("Invalid", "Helper"))
    invalid_business["website_url"] = "not-a-url"
    response = await m2_client.post("/api/v1/businesses", json=invalid_business)
    assert response.status_code == 422

    business = await create_business(m2_client, "Validation", "Helper")
    business_id = str(business["id"])
    invalid_location = location_payload("Invalid", "1 Invalid St")
    invalid_location["timezone"] = "Mars/Olympus_Mons"
    response = await m2_client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=tenant_header(business_id),
        json=invalid_location,
    )
    assert response.status_code == 422

    invalid_hours = location_payload("Invalid", "1 Invalid St")
    invalid_hours["hours"] = [
        {
            "day_of_week": 0,
            "open_time": "17:00:00",
            "close_time": "09:00:00",
            "is_closed": False,
        }
    ]
    response = await m2_client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=tenant_header(business_id),
        json=invalid_hours,
    )
    assert response.status_code == 422

    duplicate_days = location_payload("Invalid", "1 Invalid St")
    duplicate_days["hours"] = [
        {"day_of_week": 0, "is_closed": True},
        {"day_of_week": 0, "is_closed": True},
    ]
    response = await m2_client.post(
        f"/api/v1/businesses/{business_id}/locations",
        headers=tenant_header(business_id),
        json=duplicate_days,
    )
    assert response.status_code == 422
