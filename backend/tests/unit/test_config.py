"""Runtime configuration validation tests."""

import pytest
from pydantic import ValidationError

from budbot.core.config import Settings


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUDBOT_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_database_url_requires_async_postgresql() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///test.db")


def test_invalid_environment_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="environment"):
        Settings(
            _env_file=None,
            environment="staging",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )
