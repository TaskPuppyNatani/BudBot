"""Runtime configuration validation tests."""

import base64

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


def test_production_requires_a_dedicated_rate_limit_hmac_key() -> None:
    with pytest.raises(ValidationError, match="BUDBOT_ADMIN_LOGIN_RATE_LIMIT_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
        )

    with pytest.raises(ValidationError, match="BUDBOT_ADMIN_LOGIN_RATE_LIMIT_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            admin_login_rate_limit_key="too-short",
        )

    configured = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        admin_login_rate_limit_key="x" * 32,
        provider_root_key=base64.urlsafe_b64encode(bytes(range(32))).decode(),
    )
    assert configured.admin_login_rate_limit_key is not None
    assert configured.admin_login_rate_limit_key.get_secret_value() == "x" * 32


def test_production_requires_a_valid_provider_root_key() -> None:
    production = {
        "_env_file": None,
        "environment": "production",
        "database_url": "postgresql+asyncpg://user:pass@localhost/db",
        "admin_login_rate_limit_key": "x" * 32,
    }
    with pytest.raises(ValidationError, match="BUDBOT_PROVIDER_ROOT_KEY"):
        Settings(**production)

    malformed_key = "not-a-valid-key"
    with pytest.raises(ValidationError, match="BUDBOT_PROVIDER_ROOT_KEY") as error:
        Settings(**production, provider_root_key=malformed_key)
    assert malformed_key not in str(error.value)

    valid_key = base64.urlsafe_b64encode(bytes(range(32))).decode()
    configured = Settings(**production, provider_root_key=valid_key)
    assert configured.provider_root_key is not None
