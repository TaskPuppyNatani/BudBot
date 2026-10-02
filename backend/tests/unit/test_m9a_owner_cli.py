"""Owner-setup password retries preserve input and defer all owner writes."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from budbot import admin
from budbot.core.security import verify_password
from budbot.models.auth import AuthSetupState
from budbot.models.business import Business
from budbot.models.user import BusinessMembership, UserAccount

VALID_PASSWORD = "a private owner passphrase"


@pytest.mark.parametrize(
    ("passwords", "expected_error"),
    [
        ([VALID_PASSWORD, VALID_PASSWORD], ""),
        (["tiny", "tiny", VALID_PASSWORD, VALID_PASSWORD], "at least 12 characters"),
        (
            ["x" * 1025, "x" * 1025, VALID_PASSWORD, VALID_PASSWORD],
            "maximum 1024 UTF-8 bytes",
        ),
        (
            [VALID_PASSWORD, "a different private passphrase", VALID_PASSWORD, VALID_PASSWORD],
            "Passwords did not match",
        ),
    ],
    ids=["first-try-success", "short-then-valid", "too-long-then-valid", "mismatch-then-valid"],
)
async def test_owner_setup_retries_password_before_any_owner_state_is_persisted(
    passwords, expected_error, db_session, settings, monkeypatch, capsys
) -> None:
    business = Business(display_name="Selected CLI Business", industry="general_retail")
    db_session.add(business)
    await db_session.commit()

    @asynccontextmanager
    async def session_context():
        yield db_session

    database = SimpleNamespace(session_factory=session_context, dispose=AsyncMock())
    database_factory = Mock(return_value=database)
    active_businesses = AsyncMock(return_value=[business])
    supplied_input = Mock(side_effect=[" OWNER@example.test ", " First Owner ", "1"])
    remaining_passwords = iter(passwords)

    def read_password(_prompt):
        # Each rejected attempt stays entirely in the input phase. Neither the
        # write transaction nor owner-setup singleton has been touched yet.
        database_factory.assert_not_called()
        active_businesses.assert_not_awaited()
        return next(remaining_passwords)

    password_prompt = Mock(side_effect=read_password)
    monkeypatch.setattr(admin, "get_settings", lambda: settings)
    monkeypatch.setattr(admin, "Database", database_factory)
    monkeypatch.setattr(admin, "_active_businesses", active_businesses)
    monkeypatch.setattr("builtins.input", supplied_input)
    monkeypatch.setattr(admin.getpass, "getpass", password_prompt)

    result = await admin._setup_owner(admin._parser().parse_args(["setup-owner"]))

    assert result == 0
    assert password_prompt.call_count == len(passwords)
    assert supplied_input.call_count == 3  # email, name, and business only once
    active_businesses.assert_awaited_once()
    database_factory.assert_called_once_with(settings)
    database.dispose.assert_awaited_once()
    users = list((await db_session.scalars(select(UserAccount))).all())
    assert len(users) == 1
    user = users[0]
    assert (user.email, user.display_name) == ("owner@example.test", "First Owner")
    assert verify_password(user.password_hash, VALID_PASSWORD)
    memberships = list((await db_session.scalars(select(BusinessMembership))).all())
    assert [(item.user_id, item.business_id, item.role) for item in memberships] == [
        (user.id, business.id, "owner")
    ]
    state = await db_session.get(AuthSetupState, 1)
    assert state is not None and state.owner_user_id == user.id
    assert state.initialized_at is not None
    output = capsys.readouterr()
    if expected_error:
        assert expected_error in output.err
    else:
        assert output.err == ""
    assert "Owner setup completed" in output.out
    assert all(password not in output.out + output.err for password in passwords)


@pytest.mark.parametrize("cancellation", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("confirmation", [False, True], ids=["password", "confirmation"])
def test_cancelling_password_retry_exits_cleanly_without_owner_writes(
    cancellation, confirmation, settings, monkeypatch, capsys
) -> None:
    database_factory = Mock()
    active_businesses = AsyncMock()
    passwords = ["tiny", "tiny"] + ([VALID_PASSWORD] if confirmation else [])
    password_prompt = Mock(side_effect=[*passwords, cancellation()])
    monkeypatch.setattr(admin, "get_settings", lambda: settings)
    monkeypatch.setattr(admin, "Database", database_factory)
    monkeypatch.setattr(admin, "_active_businesses", active_businesses)
    monkeypatch.setattr(admin.getpass, "getpass", password_prompt)
    monkeypatch.setattr(
        "sys.argv",
        ["budbot.admin", "setup-owner", "--email", "owner@example.test", "--display-name", "Owner"],
    )

    with pytest.raises(SystemExit) as exited:
        admin.main()

    assert exited.value.code == 130
    assert password_prompt.call_count == len(passwords) + 1
    database_factory.assert_not_called()
    active_businesses.assert_not_awaited()
    output = capsys.readouterr()
    assert "Owner setup was cancelled; no setup changes were kept." in output.err
    assert "tiny" not in output.out + output.err
