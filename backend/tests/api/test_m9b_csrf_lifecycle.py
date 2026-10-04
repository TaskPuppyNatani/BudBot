"""CSRF issuance must be committed before ASGI sends a usable response.

Unlike HTTPX's normal ASGI transport, a browser can start a second request while
the first request's yield-dependency cleanup is still running. Hold that cleanup
with events, then use a separate database session for the immediate mutation.
"""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
import inspect
import json

from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from budbot.core.security import token_digest
from budbot.api.routes import auth
from budbot.database.base import Base
from budbot.models.auth import AdminSession
from conftest import TEST_OWNER_EMAIL, TEST_OWNER_PASSWORD, seed_owner


@dataclass
class ResponseProbe:
    delivered: asyncio.Event = field(default_factory=asyncio.Event)
    finalizer_waiting: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    body: dict = field(default_factory=dict)
    cookie: str | None = None
    trace: list[str] = field(default_factory=list)


_probe: ContextVar[ResponseProbe | None] = ContextVar("csrf_response_probe", default=None)


@pytest.fixture
async def csrf_race_client(application, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'csrf.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    class ObservedSession(AsyncSession):
        async def commit(self):
            probe = _probe.get()
            # Hold only the commit made by the actual yield dependency, not a
            # deliberate endpoint commit. Async calls retain this direct caller.
            if probe is not None and inspect.currentframe().f_back.f_code.co_name == "get_session":
                probe.trace.append("cleanup waiting")
                probe.finalizer_waiting.set()
                await probe.release.wait()
            await super().commit()
            if probe is not None:
                probe.trace.append("commit completed")

    factory = async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False)
    async with factory() as session:
        _owner, business = await seed_owner(session)
        business_id = str(business.id)

    async def sessions():
        async with factory() as session:
            yield session

    active_probe = None
    issuance_path = None

    async def observed_app(scope, receive, send):
        probe = active_probe if scope.get("path") == issuance_path else None
        token = _probe.set(probe)
        chunks = bytearray()
        content_length = None

        async def observed_send(message):
            nonlocal content_length
            await send(message)
            if probe is not None and message["type"] == "http.response.start":
                for name, value in message["headers"]:
                    if name == b"content-length":
                        content_length = int(value)
                    if name == b"set-cookie":
                        cookies = SimpleCookie(value.decode())
                        if "budbot_admin_session" in cookies:
                            probe.cookie = cookies["budbot_admin_session"].value
            if probe is not None and message["type"] == "http.response.body":
                chunks.extend(message["body"])
                # BaseHTTPMiddleware can send the complete Content-Length body
                # with more_body=True before a later empty terminator. Browsers
                # can consume this body without waiting for dependency cleanup.
                if not probe.delivered.is_set() and (len(chunks) == content_length or not message.get("more_body")):
                    probe.body = json.loads(chunks)
                    probe.trace.append("response delivered")
                    probe.delivered.set()

        try:
            await application(scope, receive, observed_send)
        finally:
            _probe.reset(token)

    def observe(path):
        nonlocal active_probe, issuance_path
        active_probe = ResponseProbe()
        issuance_path = path
        return active_probe

    try:
        async with application.router.lifespan_context(application):
            # Keep the actual get_session dependency and FastAPI cleanup timing.
            application.state.database.session = sessions
            async with AsyncClient(transport=ASGITransport(app=observed_app), base_url="http://testserver") as client:
                login = await client.post("/api/v1/auth/login", json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD})
                assert login.status_code == 200
                yield client, factory, business_id, observe
    finally:
        await engine.dispose()


@pytest.mark.parametrize("issuance", ["me", "login"])
@pytest.mark.parametrize("mutation", ["logout", "business"])
async def test_issued_csrf_is_usable_before_request_cleanup(csrf_race_client, issuance, mutation):
    client, factory, business_id, observe = csrf_race_client
    path = f"/api/v1/auth/{issuance}"
    probe = observe(path)
    task = asyncio.create_task(client.get(path) if issuance == "me" else client.post(path,
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD}))
    try:
        await asyncio.wait_for(probe.delivered.wait(), timeout=5)
        await asyncio.wait_for(probe.finalizer_waiting.wait(), timeout=5)
        assert not task.done(), "The unsafe request must precede yield-dependency cleanup"
        csrf = probe.body["csrf_token"]
        # Consume login's emitted cookie before HTTPX waits for app cleanup.
        cookie = probe.cookie if issuance == "login" else client.cookies.get("budbot_admin_session")
        async with AsyncClient(transport=client._transport, base_url="http://testserver",
            cookies={"budbot_admin_session": cookie}) as immediate:
            if mutation == "logout":
                result = await immediate.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
                assert result.status_code == 204, (result.text, probe.trace)
            else:
                result = await immediate.patch(f"/api/v1/businesses/{business_id}",
                    headers={"X-CSRF-Token": csrf}, json={"display_name": "Immediate CSRF update"})
                assert result.status_code == 200, (result.text, probe.trace)
        assert probe.trace.index("commit completed") < probe.trace.index("response delivered")
        async with factory() as observer:
            record = await observer.scalar(select(AdminSession).where(AdminSession.token_digest == token_digest(cookie)))
            assert record is not None and record.csrf_digest == token_digest(csrf)
    finally:
        probe.release.set()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("issuance", ["me", "login"])
async def test_failed_session_response_rolls_back_unpublished_csrf(csrf_race_client, monkeypatch, issuance):
    client, factory, _business_id, _observe = csrf_race_client
    async with factory() as observer:
        before = list((await observer.execute(select(AdminSession.token_digest, AdminSession.csrf_digest))).all())

    async def fail_response(*args, **kwargs):
        raise HTTPException(status_code=403, detail="Synthetic response construction failure.")

    monkeypatch.setattr(auth, "_session_read", fail_response)
    path = f"/api/v1/auth/{issuance}"
    result = await client.get(path) if issuance == "me" else await client.post(path,
        json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD})
    assert result.status_code == 403
    assert "csrf_token" not in result.json()
    assert "set-cookie" not in result.headers
    async with factory() as observer:
        after = list((await observer.execute(select(AdminSession.token_digest, AdminSession.csrf_digest))).all())
        assert after == before
