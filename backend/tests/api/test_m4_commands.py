"""M4 customer command API and public error behavior."""

from httpx import AsyncClient


def _business_payload(name: str) -> dict[str, object]:
    return {
        "display_name": name,
        "industry": "general_retail",
        "assistant": {
            "display_name": f"{name} Guide",
            "greeting": "Welcome",
            "fallback_message": "Ask a team member.",
            "enabled": True,
        },
    }


def _tenant_header(business_id: str) -> dict[str, str]:
    return {"X-BudBot-Business-ID": business_id}


async def _business(client: AsyncClient, name: str) -> dict[str, object]:
    response = await client.post("/api/v1/businesses", json=_business_payload(name))
    assert response.status_code == 201, response.text
    return response.json()


async def _session(client: AsyncClient, business_id: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/sessions", headers=_tenant_header(business_id), json={}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_customer_help_and_autocomplete_expose_only_real_commands(
    m2_client: AsyncClient,
) -> None:
    business = await _business(m2_client, "Cedar")
    business_id = str(business["id"])
    customer_session = await _session(m2_client, business_id)
    session_id = str(customer_session["id"])

    executed = await m2_client.post(
        "/api/v1/commands/execute",
        headers=_tenant_header(business_id),
        json={"session_id": session_id, "input": " /HELP "},
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["canonical_name"] == "help"
    assert body["output"].startswith("Cedar Guide commands:")
    assert [command["name"] for command in body["commands"]] == ["help"]
    assert "/products" not in body["output"]

    metadata = await m2_client.get(
        "/api/v1/commands",
        headers=_tenant_header(business_id),
        params={"session_id": session_id},
    )
    assert metadata.status_code == 200
    assert metadata.json() == [
        {
            "name": "help",
            "description": "Show commands available in the current customer context.",
            "aliases": [],
            "scope": "customer",
            "argument_hint": "",
            "available": True,
        }
    ]


async def test_command_api_normalizes_invalid_unknown_and_cross_tenant_errors(
    m2_client: AsyncClient,
) -> None:
    first = await _business(m2_client, "First")
    second = await _business(m2_client, "Second")
    first_id = str(first["id"])
    second_id = str(second["id"])
    customer_session = await _session(m2_client, first_id)
    session_id = str(customer_session["id"])

    ordinary = await m2_client.post(
        "/api/v1/commands/execute",
        headers=_tenant_header(first_id),
        json={"session_id": session_id, "input": "hello"},
    )
    assert ordinary.status_code == 400
    assert ordinary.json()["code"] == "COMMAND_INVALID"

    unknown = await m2_client.post(
        "/api/v1/commands/execute",
        headers=_tenant_header(first_id),
        json={"session_id": session_id, "input": "/products"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "COMMAND_NOT_FOUND"

    cross_tenant = await m2_client.post(
        "/api/v1/commands/execute",
        headers=_tenant_header(second_id),
        json={"session_id": session_id, "input": "/help"},
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["code"] == "SESSION_NOT_FOUND"
