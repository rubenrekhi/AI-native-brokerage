import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import worker as app_worker


class _FakeWorker:
    """Stand-in with just the attributes `_safe_close` reads."""

    def __init__(
        self,
        *,
        delete_side_effect=None,
        close_side_effect=None,
        on_shutdown=None,
    ):
        self._handle_signals = True
        self._pool = object()
        self.tasks = {}
        self.health_check_key = "arq:queue:health-check"
        self.ctx = {}
        self.on_shutdown = on_shutdown

        self.pool = MagicMock()
        self.pool.delete = AsyncMock(side_effect=delete_side_effect)
        self.pool.close = AsyncMock(side_effect=close_side_effect)


async def _run_close(worker):
    await app_worker._safe_close(worker)


class TestSafeCloseSwallowsCleanupErrors:
    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("Timeout connecting to server"),
            ConnectionError("Connection closed by server"),
            asyncio.CancelledError(),
        ],
    )
    async def test_delete_health_check_key_swallowed(self, exc):
        worker = _FakeWorker(delete_side_effect=exc)
        await _run_close(worker)
        worker.pool.delete.assert_awaited_once_with("arq:queue:health-check")
        worker.pool.close.assert_awaited_once_with(close_connection_pool=True)
        assert worker._pool is None

    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError(),
            ConnectionError(),
            asyncio.CancelledError(),
        ],
    )
    async def test_pool_close_swallowed(self, exc):
        worker = _FakeWorker(close_side_effect=exc)
        await _run_close(worker)
        worker.pool.close.assert_awaited_once_with(close_connection_pool=True)
        assert worker._pool is None


class TestSafeClosePropagatesRealErrors:
    async def test_unrelated_exception_in_delete_propagates(self):
        worker = _FakeWorker(delete_side_effect=ValueError("boom"))
        with pytest.raises(ValueError, match="boom"):
            await _run_close(worker)

    async def test_unrelated_exception_in_pool_close_propagates(self):
        worker = _FakeWorker(close_side_effect=RuntimeError("bad pool"))
        with pytest.raises(RuntimeError, match="bad pool"):
            await _run_close(worker)

    async def test_on_shutdown_hook_errors_propagate(self):
        async def failing_hook(ctx):
            raise TimeoutError("hook failed")

        worker = _FakeWorker(on_shutdown=failing_hook)
        with pytest.raises(TimeoutError, match="hook failed"):
            await _run_close(worker)
        # delete ran, pool.close did not
        worker.pool.delete.assert_awaited_once()
        worker.pool.close.assert_not_awaited()


class TestSafeCloseHappyPath:
    async def test_all_steps_execute_in_order(self):
        calls = []
        worker = _FakeWorker()
        worker.pool.delete = AsyncMock(side_effect=lambda *_: calls.append("delete"))

        async def hook(ctx):
            calls.append("on_shutdown")

        worker.on_shutdown = hook
        worker.pool.close = AsyncMock(side_effect=lambda **_: calls.append("close"))

        await _run_close(worker)

        assert calls == ["delete", "on_shutdown", "close"]
        assert worker._pool is None

    async def test_noop_when_pool_already_closed(self):
        worker = _FakeWorker()
        worker._pool = None
        await _run_close(worker)
        worker.pool.delete.assert_not_awaited()
        worker.pool.close.assert_not_awaited()


class TestMonkeyPatchInstalled:
    def test_arq_worker_close_replaced(self):
        from arq import worker as arq_worker

        assert arq_worker.Worker.close is app_worker._safe_close
