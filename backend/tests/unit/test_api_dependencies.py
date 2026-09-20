"""Request transaction lifecycle tests."""

from types import SimpleNamespace

import pytest

from budbot.api.dependencies import get_session


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.fake_session = session

    async def session(self):
        yield self.fake_session


def request_with(session: FakeSession) -> object:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=FakeDatabase(session)))
    )


async def test_request_session_commits_after_success() -> None:
    session = FakeSession()
    dependency = get_session(request_with(session))  # type: ignore[arg-type]
    assert await anext(dependency) is session

    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert session.commits == 1
    assert session.rollbacks == 0


async def test_request_session_rolls_back_and_reraises_failure() -> None:
    session = FakeSession()
    dependency = get_session(request_with(session))  # type: ignore[arg-type]
    assert await anext(dependency) is session

    with pytest.raises(RuntimeError, match="request failed"):
        await dependency.athrow(RuntimeError("request failed"))

    assert session.commits == 0
    assert session.rollbacks == 1
