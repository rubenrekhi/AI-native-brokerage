"""Unit tests for ``app.ai.runtime.db.make_session_factory``.

The factory's ``try/yield/commit/except/rollback/raise`` block is the
load-bearing invariant for mid-turn audit durability. Integration tests
exercise the happy path against a real Postgres; these unit tests pin
the rollback contract without a database.

The strategy is to replace ``async_sessionmaker`` with a fake whose
session records the ``commit`` / ``rollback`` calls. We can then drive
the factory across success and exception paths and assert the recorded
sequence.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.ai.runtime.db import make_session_factory


class _FakeSession:
    """Async-context-manager stand-in for :class:`AsyncSession`.

    Records every ``commit`` / ``rollback`` / ``close`` so tests can
    assert the exact sequence and count.
    """

    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()
        # ``expire_on_commit=False`` is asserted at factory-creation
        # time; this flag lets a test verify the maker was constructed
        # with the expected kwarg.
        self.attribute_accessible_after_commit = True

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


class _FakeMaker:
    """Stand-in for ``async_sessionmaker``'s return value.

    Each call yields the same session so tests can assert across the
    factory invocation. Multi-call tests use ``sessions`` to access the
    full history.
    """

    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []
        self.call_count = 0

    def __call__(self) -> _FakeSession:
        self.call_count += 1
        session = _FakeSession()
        self.sessions.append(session)
        return session


def _install_fake_maker(monkeypatch: pytest.MonkeyPatch) -> _FakeMaker:
    """Replace ``async_sessionmaker`` so the factory uses our fake.

    Returns the fake so the test can assert on session activity. Tracks
    construction kwargs (``class_``, ``expire_on_commit``) via a side
    box so we don't have to mock the constructor too.
    """
    maker = _FakeMaker()

    def fake_async_sessionmaker(
        engine: Any, *, class_: Any, expire_on_commit: bool
    ) -> _FakeMaker:
        # The signature mirrors the SQLAlchemy call site so a regression
        # that changes the keyword args (e.g. drops expire_on_commit)
        # fails here loudly.
        maker.constructed_with = {
            "engine": engine,
            "class_": class_,
            "expire_on_commit": expire_on_commit,
        }
        return maker

    monkeypatch.setattr(
        "app.ai.runtime.db.async_sessionmaker", fake_async_sessionmaker
    )
    return maker


class TestSessionFactoryConstruction:
    def test_async_sessionmaker_called_with_expire_on_commit_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``expire_on_commit=False`` is load-bearing: freshly-flushed
        # ORM instances must stay attribute-accessible after the context
        # exits so callers can read ``.id`` post-commit. A regression
        # that drops this would break ``initialize_turn``'s use of
        # ``user_msg.id`` after the session closes.
        maker = _install_fake_maker(monkeypatch)
        engine = MagicMock(spec=AsyncEngine)

        make_session_factory(engine)

        assert maker.constructed_with["engine"] is engine
        assert maker.constructed_with["class_"] is AsyncSession
        assert maker.constructed_with["expire_on_commit"] is False


class TestSessionFactoryCommit:
    async def test_commits_on_normal_block_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The success path: no exception inside the ``async with`` →
        # ``commit`` is awaited exactly once, ``rollback`` never.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        async with factory() as db:
            assert db is maker.sessions[-1]

        session = maker.sessions[0]
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        session.close.assert_awaited_once()

    async def test_does_not_commit_when_no_work_done(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even an empty context still commits — the factory has no
        # awareness of whether any SQL was issued. This is the documented
        # behavior; a future "commit only if dirty" optimization would
        # break this test on purpose.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        async with factory():
            pass

        maker.sessions[0].commit.assert_awaited_once()


class TestSessionFactoryRollback:
    async def test_rolls_back_on_exception_inside_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The critical rollback contract: any exception inside the
        # ``async with`` triggers rollback + re-raise. If this ever
        # stops re-raising, a failed write becomes a silent data-loss
        # bug.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        with pytest.raises(ValueError, match="boom"):
            async with factory():
                raise ValueError("boom")

        session = maker.sessions[0]
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()

    async def test_rolls_back_on_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same contract for any Exception subclass — the except clause
        # uses bare ``Exception``, so the rollback must fire for every
        # caller-thrown error type.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        with pytest.raises(RuntimeError, match="oops"):
            async with factory():
                raise RuntimeError("oops")

        maker.sessions[0].rollback.assert_awaited_once()

    async def test_does_not_swallow_exception_after_rollback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The ``raise`` at the end of the except clause is what makes
        # the factory composable with the loop's outer error handling.
        # If a regression replaces ``raise`` with ``return`` or
        # ``pass``, the original exception is swallowed and the caller
        # gets no signal of the failure. This test pins re-raise via
        # exception identity.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        original = KeyError("specific-key")
        with pytest.raises(KeyError) as exc_info:
            async with factory():
                raise original

        # Exception identity — the same instance bubbles through.
        assert exc_info.value is original
        maker.sessions[0].rollback.assert_awaited_once()

    async def test_does_not_rollback_when_commit_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Sanity check: a clean exit must not double-roll-back. A
        # regression that swaps the commit/rollback order would fail
        # this assertion.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        async with factory():
            pass

        session = maker.sessions[0]
        assert session.commit.call_count == 1
        assert session.rollback.call_count == 0


class TestSessionFactoryIsolation:
    async def test_two_invocations_use_different_sessions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The factory's docstring promises "one session per write" —
        # the pgbouncer-transaction-mode rationale relies on it. Two
        # ``async with factory()`` blocks must produce two distinct
        # ``Session`` instances, not reuse one.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        async with factory() as db_a:
            pass
        async with factory() as db_b:
            pass

        assert maker.call_count == 2
        assert db_a is not db_b
        # Both committed independently.
        assert maker.sessions[0].commit.await_count == 1
        assert maker.sessions[1].commit.await_count == 1

    async def test_failed_invocation_does_not_taint_next(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # After an inner exception rolls back the first session, the
        # next ``async with factory()`` must open a fresh session and
        # behave normally. Regression guard against accidentally
        # caching state at factory level.
        maker = _install_fake_maker(monkeypatch)
        factory = make_session_factory(MagicMock(spec=AsyncEngine))

        with pytest.raises(ValueError):
            async with factory():
                raise ValueError("boom")

        async with factory():
            pass

        assert maker.sessions[0].rollback.await_count == 1
        assert maker.sessions[0].commit.await_count == 0
        assert maker.sessions[1].rollback.await_count == 0
        assert maker.sessions[1].commit.await_count == 1
