"""Owner/CSRF gateway exercised against an isolated fake Unix controller."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from budbot.api.dependencies import get_session
from budbot.main import create_app
from budbot.models.auth import AuditEvent
from budbot.models.user import BusinessMembership
from budbot.services import local_runtime_service
from conftest import TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD, seed_owner


@pytest.fixture
async def runtime_client(settings, db_session, tmp_path, monkeypatch):
    app = create_app(settings.model_copy(update={"environment": "development"}))
    async def session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
    app.dependency_overrides[get_session] = session
    path = tmp_path / "control.sock"
    monkeypatch.setattr(local_runtime_service, "SOCKET_PATH", path)
    commands = []
    async def handle(reader, writer):
        command = await reader.readline()
        commands.append(command)
        writer.write(b"running\n" if command == b"status\n" else b"accepted\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_unix_server(handle, path)
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
                _, business = await seed_owner(db_session)
                login = await client.post("/api/v1/auth/login", json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD})
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                yield SimpleNamespace(client=client, db=db_session, app=app, commands=commands, server=server,
                    bid=business.id, base=f"/api/v1/businesses/{business.id}/local-runtime")
    finally:
        server.close()
        await server.wait_closed()


async def test_owner_capability_shutdown_and_audit_are_safe(runtime_client):
    f = runtime_client
    status = await f.client.get(f.base)
    assert status.status_code == 200 and status.json() == {"available": True, "state": "running"}
    assert status.headers["cache-control"] == "no-store"
    for _ in range(2):
        response = await f.client.post(f.base + "/shutdown", json={})
        assert response.status_code == 202 and response.json() == {"state": "stopping"}
    assert f.commands == [b"status\n", b"shutdown\n", b"shutdown\n"]
    events = list((await f.db.scalars(select(AuditEvent).where(AuditEvent.event_type == "admin.local_runtime.shutdown_requested"))).all())
    assert len(events) == 2 and all(row.business_id == f.bid and row.details == {} for row in events)


async def test_normal_production_has_no_runtime_routes(settings):
    app = create_app(settings.model_copy(update={"environment": "production",
        "admin_login_rate_limit_key": SecretStr("synthetic-production-test-key-123456789")}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        base = f"/api/v1/businesses/{uuid4()}/local-runtime"
        assert (await client.get(base)).status_code == 404
        assert (await client.post(base + "/shutdown", json={})).status_code == 404
    assert not any("local-runtime" in path for path in app.openapi()["paths"])


@pytest.mark.parametrize("role", ["admin", "manager", "viewer", "unknown"])
async def test_only_owner_membership_can_access_runtime(runtime_client, role):
    f = runtime_client
    membership = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == f.bid))
    membership.role = role
    await f.db.commit()
    assert (await f.client.get(f.base)).status_code == 403
    assert (await f.client.post(f.base + "/shutdown", json={})).status_code == 403
    assert f.commands == []


@pytest.mark.parametrize("failure", ["unauthenticated", "csrf_missing", "csrf_invalid", "cross_tenant", "origin", "host"])
async def test_auth_tenancy_csrf_and_local_origin_are_required(runtime_client, failure):
    f = runtime_client
    path = f.base + "/shutdown"
    headers = {"X-BudBot-Business-ID": str(f.bid)}
    expected = 403
    if failure == "unauthenticated":
        f.client.cookies.clear()
        expected = 401
    elif failure == "csrf_missing":
        f.client.headers.pop("X-CSRF-Token")
    elif failure == "csrf_invalid":
        headers["X-CSRF-Token"] = "invalid"
    elif failure == "cross_tenant":
        path = path.replace(str(f.bid), str(uuid4()))
        expected = 404
    elif failure == "origin":
        headers["Origin"] = "https://untrusted.example"
    else:
        headers["Host"] = "public.example"
        expected = 404
    assert (await f.client.post(path, json={}, headers=headers)).status_code == expected
    assert f.commands == []


@pytest.mark.parametrize("payload", [{"command": "down -v synthetic-secret"}, {"action": "restart"}, [], "shutdown"])
async def test_payload_cannot_select_actions_or_arguments(runtime_client, payload):
    f = runtime_client
    result = await f.client.post(f.base + "/shutdown", json=payload)
    assert result.status_code == 422 and "synthetic-secret" not in result.text
    assert f.commands == []


async def test_no_controller_means_no_capability_and_safe_shutdown_error(runtime_client):
    f = runtime_client
    f.server.close()
    await f.server.wait_closed()
    result = await f.client.get(f.base)
    assert result.json() == {"available": False, "state": "unavailable"}
    result = await f.client.post(f.base + "/shutdown")
    assert result.status_code == 503 and result.json()["code"] == "LOCAL_RUNTIME_UNAVAILABLE"
    assert "control.sock" not in result.text and "/tmp/" not in result.text


async def test_failed_audit_commit_does_not_signal_shutdown(runtime_client):
    f = runtime_client
    with patch.object(f.db, "commit", new=AsyncMock(side_effect=RuntimeError("synthetic commit failure"))):
        with pytest.raises(RuntimeError):
            await f.client.post(f.base + "/shutdown", json={})
    assert f.commands == []
