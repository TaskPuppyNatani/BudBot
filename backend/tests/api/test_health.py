"""Liveness and readiness API tests."""

from fastapi import FastAPI
from httpx import AsyncClient

from budbot.api.dependencies import get_database


class ReadyDatabase:
    async def ping(self, timeout_seconds: float) -> None:
        assert timeout_seconds == 0.1


class UnavailableDatabase:
    async def ping(self, timeout_seconds: float) -> None:
        raise OSError("test database unavailable")


async def get_ready_database() -> ReadyDatabase:
    return ReadyDatabase()


async def get_unavailable_database() -> UnavailableDatabase:
    return UnavailableDatabase()


async def test_health_is_stable_and_does_not_require_database(
    client: AsyncClient,
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_database_ready(
    client: AsyncClient, application: FastAPI
) -> None:
    application.dependency_overrides[get_database] = get_ready_database

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok"},
    }


async def test_readiness_fails_closed_without_leaking_error(
    client: AsyncClient, application: FastAPI
) -> None:
    application.dependency_overrides[get_database] = get_unavailable_database

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
    assert "test database unavailable" not in response.text
