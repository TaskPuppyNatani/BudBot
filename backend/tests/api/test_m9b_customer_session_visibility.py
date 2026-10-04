"""Customer mutations must be visible before their HTTP body is delivered.

Hold the real yield dependency's cleanup with events, then issue the widget's
next request in a separate database session. Normal ASGITransport alone waits
for cleanup and hides this race. SQLite checks response/commit ordering here;
it does not establish PostgreSQL's concurrent isolation behavior.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
import inspect
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from budbot.api.routes import sessions as session_routes
from budbot.core.time import utc_now
from budbot.database.base import Base
from budbot.models.assistant import AssistantConfiguration, LocationAssistantOverride
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.session import CustomerSession


@dataclass
class ResponseProbe:
    delivered: asyncio.Event = field(default_factory=asyncio.Event)
    finalizer_waiting: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    body: dict = field(default_factory=dict)
    status: int | None = None
    trace: list[str] = field(default_factory=list)


_probe: ContextVar[ResponseProbe | None] = ContextVar("customer_response_probe", default=None)


@pytest.fixture
async def customer_race_client(application, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'customer.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    class ObservedSession(AsyncSession):
        async def commit(self):
            probe = _probe.get()
            # Block dependency cleanup only; deliberate endpoint commits run.
            if probe is not None and inspect.currentframe().f_back.f_code.co_name == "get_session":
                probe.trace.append("cleanup waiting")
                probe.finalizer_waiting.set()
                await probe.release.wait()
            await super().commit()
            if probe is not None:
                probe.trace.append("commit completed")

    factory = async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False)
    async with factory() as session:
        business = Business(
            display_name="Customer Shop", industry="cannabis",
            compliance_domain="cannabis", compliance_profile_id="oregon_cannabis",
            assistant_configuration=AssistantConfiguration(
                display_name="Shop Helper", greeting="Welcome.",
                fallback_message="Ask a team member.", enabled=True,
            ),
        )
        other = Business(display_name="Other tenant", industry="general_retail")
        session.add_all([business, other])
        await session.flush()
        location = Location(
            business_id=business.id, display_name="Main", address_line_1="10 Main St",
            city="Portland", region="Oregon", region_code="OR", postal_code="97201",
            country="US", timezone="America/Los_Angeles", active=True,
        )
        session.add(location)
        await session.flush()
        session.add(LocationAssistantOverride(
            business_id=business.id, location_id=location.id,
            display_name="Main Helper", greeting="Welcome to Main.",
        ))
        await session.commit()
        business_id, other_id, location_id = str(business.id), str(other.id), str(location.id)

    async def sessions():
        async with factory() as session:
            yield session

    active_probe = None
    observed_request = None

    async def observed_app(scope, receive, send):
        probe = active_probe if (scope.get("method"), scope.get("path")) == observed_request else None
        token = _probe.set(probe)
        chunks = bytearray()
        content_length = None

        async def observed_send(message):
            nonlocal content_length
            await send(message)
            if probe is not None and message["type"] == "http.response.start":
                probe.status = message["status"]
                for name, value in message["headers"]:
                    if name == b"content-length":
                        content_length = int(value)
            if probe is not None and message["type"] == "http.response.body":
                chunks.extend(message["body"])
                # Middleware may send the complete Content-Length body with
                # more_body=True, before cleanup and the empty terminator.
                if not probe.delivered.is_set() and (len(chunks) == content_length or not message.get("more_body")):
                    probe.body = json.loads(chunks)
                    probe.trace.append("response delivered")
                    probe.delivered.set()

        try:
            await application(scope, receive, observed_send)
        finally:
            _probe.reset(token)

    def observe(method, path):
        nonlocal active_probe, observed_request
        active_probe = ResponseProbe()
        observed_request = (method, path)
        return active_probe

    try:
        async with application.router.lifespan_context(application):
            application.state.database.session = sessions
            async with AsyncClient(
                transport=ASGITransport(app=observed_app), base_url="http://testserver",
                headers={"X-BudBot-Business-ID": business_id},
            ) as client:
                yield client, factory, location_id, other_id, observe
    finally:
        await engine.dispose()


@pytest.mark.parametrize("next_request", ["widget", "session", "location"])
async def test_created_session_visible_before_cleanup(customer_race_client, next_request):
    client, _factory, location_id, _other_id, observe = customer_race_client
    probe = observe("POST", "/api/v1/sessions")
    task = asyncio.create_task(client.post("/api/v1/sessions", json={}))
    try:
        await asyncio.wait_for(probe.delivered.wait(), timeout=5)
        await asyncio.wait_for(probe.finalizer_waiting.wait(), timeout=5)
        assert probe.status == 201
        assert not task.done(), "Follow-up must run before dependency cleanup"
        path = f"/api/v1/sessions/{probe.body['id']}"
        if next_request == "location":
            result = await client.patch(f"{path}/location", json={"selected_location_id": location_id})
            assert result.status_code == 200, (result.text, probe.trace)
            assert result.json()["selected_location_id"] == location_id
        else:
            result = await client.get(f"{path}/widget" if next_request == "widget" else path)
            assert result.status_code == 200, (result.text, probe.trace)
            if next_request == "widget":
                assert result.json()["business"]["display_name"] == "Customer Shop"
            else:
                assert result.json()["id"] == probe.body["id"]
        assert probe.trace.index("commit completed") < probe.trace.index("response delivered")
    finally:
        probe.release.set()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("mutation", ["location", "age-attestation"])
async def test_customer_update_visible_before_cleanup(customer_race_client, mutation):
    client, _factory, location_id, _other_id, observe = customer_race_client
    created = await client.post("/api/v1/sessions", json=(
        {"selected_location_id": location_id} if mutation == "age-attestation" else {}
    ))
    assert created.status_code == 201
    path = f"/api/v1/sessions/{created.json()['id']}"
    if mutation == "age-attestation":
        blocked = await client.post("/api/v1/commands/execute", json={"session_id": created.json()["id"], "input": "/products"})
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "AGE_VERIFICATION_REQUIRED"
    method = "PATCH" if mutation == "location" else "POST"
    probe = observe(method, f"{path}/{mutation}")
    payload = {"selected_location_id": location_id} if mutation == "location" else {"confirmed_21_or_older": True}
    task = asyncio.create_task(client.request(method, f"{path}/{mutation}", json=payload))
    try:
        await asyncio.wait_for(probe.delivered.wait(), timeout=5)
        await asyncio.wait_for(probe.finalizer_waiting.wait(), timeout=5)
        assert probe.status == 200
        assert not task.done()
        result = await client.get(path)
        assert result.status_code == 200
        if mutation == "location":
            assert result.json()["selected_location_id"] == location_id
            widget = await client.get(f"{path}/widget")
            assert widget.status_code == 200
            assert widget.json()["assistant"]["display_name"] == "Main Helper"
            assert result.json()["age_gate_status"] == "REQUIRED_UNVERIFIED"
        else:
            assert result.json()["age_gate_status"] == "VERIFIED"
            assert result.json()["age_attested_at"] is not None
            allowed = await client.post("/api/v1/commands/execute", json={"session_id": created.json()["id"], "input": "/products"})
            assert allowed.status_code == 200, allowed.text
        assert probe.trace.index("commit completed") < probe.trace.index("response delivered")
    finally:
        probe.release.set()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("failure", ["after_flush", "response_validation", "commit"])
async def test_failed_creation_rolls_back_unpublished_session(customer_race_client, monkeypatch, failure):
    client, factory, _location_id, _other_id, _observe = customer_race_client
    original_create = session_routes.SessionService.create

    async def fail_after_flush(self, payload):
        await original_create(self, payload)
        raise HTTPException(status_code=422, detail="Synthetic failure after creation flush.")

    def fail_validation(_customer):
        raise HTTPException(status_code=422, detail="Synthetic response validation failure.")

    async def fail_commit(_session):
        raise HTTPException(status_code=503, detail="Synthetic commit failure.")

    if failure == "after_flush":
        monkeypatch.setattr(session_routes.SessionService, "create", fail_after_flush)
    elif failure == "response_validation":
        monkeypatch.setattr(session_routes.CustomerSessionRead, "model_validate", fail_validation)
    else:
        monkeypatch.setattr(factory.class_, "commit", fail_commit)
    result = await client.post("/api/v1/sessions", json={})
    assert result.status_code == (503 if failure == "commit" else 422)
    assert "id" not in result.json()
    async with factory() as observer:
        assert await observer.scalar(select(CustomerSession.id)) is None


@pytest.mark.parametrize("failure", ["cross_tenant", "missing", "expired"])
async def test_session_boundaries_remain_enforced(customer_race_client, failure):
    client, factory, location_id, other_id, _observe = customer_race_client
    created = await client.post("/api/v1/sessions", json={"selected_location_id": location_id})
    assert created.status_code == 201
    session_id = created.json()["id"]
    if failure == "cross_tenant":
        client.headers["X-BudBot-Business-ID"] = other_id
    elif failure == "missing":
        session_id = str(uuid4())
    else:
        async with factory() as writer:
            record = await writer.get(CustomerSession, UUID(session_id))
            record.expires_at = utc_now() - timedelta(seconds=1)
            await writer.commit()
    path = f"/api/v1/sessions/{session_id}"
    if failure != "expired":
        read = await client.get(path)
        assert read.status_code == 404
    responses = [
        await client.get(f"{path}/widget"),
        await client.patch(f"{path}/location", json={"selected_location_id": location_id}),
        await client.post(f"{path}/age-attestation", json={"confirmed_21_or_older": True}),
    ]
    for response in responses:
        assert response.status_code == (410 if failure == "expired" else 404), response.text
        if failure == "expired":
            assert response.json()["code"] == "SESSION_EXPIRED"
