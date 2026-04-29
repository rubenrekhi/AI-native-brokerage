import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

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
            RedisTimeoutError("Timeout connecting to server"),
            RedisConnectionError("Connection closed by server"),
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
            RedisTimeoutError(),
            RedisConnectionError(),
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


class TestSafeClosePropagatesCancellation:
    async def test_cancelled_during_delete_reraises(self):
        worker = _FakeWorker(delete_side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await _run_close(worker)
        # pool.close should NOT run when delete was cancelled
        worker.pool.close.assert_not_awaited()

    async def test_cancelled_during_pool_close_reraises(self):
        worker = _FakeWorker(close_side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await _run_close(worker)
        worker.pool.close.assert_awaited_once_with(close_connection_pool=True)


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


class TestWorkerStartup:
    """The startup hook initializes shared resources and spawns listener
    tasks. Every resource it creates needs to end up on ``ctx`` so the
    shutdown hook and the liveness cron can reach them later."""

    async def test_startup_clears_arq_logger_handlers(self, monkeypatch):
        """arq's CLI installs a handler on the 'arq' logger after our root
        logger is configured, causing double-logging. Startup must strip it
        so arq logs flow through our root structlog formatter only."""
        monkeypatch.setattr(
            "app.worker.AlpacaBrokerService",
            MagicMock(return_value=AsyncMock()),
        )
        monkeypatch.setattr(
            "app.worker.build_listeners", MagicMock(return_value=[])
        )
        monkeypatch.setattr(app_worker.settings, "sentry_dsn", "")

        arq_logger = logging.getLogger("arq")
        stand_in = logging.StreamHandler()
        arq_logger.addHandler(stand_in)
        try:
            await app_worker.startup({})
            assert stand_in not in arq_logger.handlers
            assert arq_logger.handlers == []
        finally:
            # In case the assertion failed and the handler is still attached.
            if stand_in in arq_logger.handlers:
                arq_logger.removeHandler(stand_in)

    async def test_startup_stashes_broker_listeners_and_tasks_in_ctx(
        self, monkeypatch
    ):
        """Happy path: startup creates an AlpacaBrokerService, calls
        build_listeners, spawns one task per listener, and stashes all three
        on ctx."""
        fake_broker = AsyncMock()
        monkeypatch.setattr(
            "app.worker.AlpacaBrokerService",
            MagicMock(return_value=fake_broker),
        )
        monkeypatch.setattr(
            "app.worker.build_listeners", MagicMock(return_value=[])
        )
        # Skip sentry init path — no DSN configured.
        monkeypatch.setattr(app_worker.settings, "sentry_dsn", "")

        ctx: dict = {}
        await app_worker.startup(ctx)

        assert ctx["alpaca"] is fake_broker
        assert ctx["listeners"] == []
        assert ctx["listener_tasks"] == []

    @pytest.mark.parametrize(
        "env_setting,railway_env,expected",
        [
            ("staging", "pr-789", "pr-789"),  # PR preview overrides
            ("prod", "production", "prod"),  # real prod NOT rewritten
        ],
    )
    async def test_startup_passes_sentry_environment_to_init(
        self, monkeypatch, env_setting, railway_env, expected
    ):
        """Worker wires ``settings.sentry_environment`` into
        ``sentry_sdk.init``. The "real prod" parametrization is the
        load-bearing case: Railway's prod env name is "production" but
        ``settings.environment`` normalizes to "prod" — the override must
        NOT rewrite "prod" → "production", or existing Sentry alerts keyed
        on ``environment=prod`` silently stop matching. See SEV-433."""
        init_mock = MagicMock()
        monkeypatch.setattr(app_worker.sentry_sdk, "init", init_mock)
        monkeypatch.setattr(app_worker.sentry_sdk, "set_tag", MagicMock())
        monkeypatch.setattr(app_worker.settings, "sentry_dsn", "fake-dsn")
        monkeypatch.setattr(app_worker.settings, "environment", env_setting)
        monkeypatch.setattr(
            app_worker.settings, "railway_environment_name", railway_env
        )
        monkeypatch.setattr(
            "app.worker.AlpacaBrokerService",
            MagicMock(return_value=AsyncMock()),
        )
        monkeypatch.setattr(
            "app.worker.build_listeners", MagicMock(return_value=[])
        )

        await app_worker.startup({})

        init_mock.assert_called_once()
        assert init_mock.call_args.kwargs["environment"] == expected

    async def test_startup_spawns_asyncio_task_per_listener(self, monkeypatch):
        """Each registered listener gets its own long-running asyncio.Task."""
        fake_broker = AsyncMock()

        async def _forever():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        listener = MagicMock()
        listener.stream_name = "fake_stream"
        # Crucially: run() returns a coroutine the worker will wrap in a Task.
        listener.run = MagicMock(side_effect=lambda: _forever())

        monkeypatch.setattr(
            "app.worker.AlpacaBrokerService",
            MagicMock(return_value=fake_broker),
        )
        monkeypatch.setattr(
            "app.worker.build_listeners", MagicMock(return_value=[listener])
        )
        monkeypatch.setattr(app_worker.settings, "sentry_dsn", "")

        ctx: dict = {}
        await app_worker.startup(ctx)

        assert len(ctx["listener_tasks"]) == 1
        task = ctx["listener_tasks"][0]
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "sse-fake_stream"
        assert not task.done()  # still running

        # Clean up so pytest doesn't complain about pending tasks.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestWorkerShutdown:
    """The shutdown hook cancels listener tasks, gracefully waits for them
    with a bounded timeout, fires a Sentry alert if they hang, and closes
    the Alpaca broker's httpx client. Failures during cleanup must not
    propagate — a hung shutdown blocks Railway redeploys."""

    async def test_shutdown_cancels_tasks_and_closes_broker(self):
        """Happy path: listener exits cleanly on cancel, broker is closed."""

        async def _cooperative_listener():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_cooperative_listener())
        await asyncio.sleep(0)  # let it reach the sleep

        broker = AsyncMock()
        ctx = {
            "alpaca": broker,
            "listeners": [],
            "listener_tasks": [task],
        }

        await app_worker.shutdown(ctx)

        assert task.cancelled() or task.done()
        broker.close.assert_awaited_once()

    async def test_shutdown_fires_sentry_capture_message_on_timeout(
        self, monkeypatch
    ):
        """If a listener ignores cancellation long enough to exceed the
        shutdown timeout, shutdown must (a) not hang forever and (b) fire a
        warning-level Sentry alert so ops notice without digging through
        Railway logs."""
        capture = MagicMock()
        monkeypatch.setattr("app.worker.sentry_sdk.capture_message", capture)

        # Deterministic timeout: patch wait_for to raise immediately. Cancel
        # the gather future so its underlying tasks don't leak.
        async def _timeout_immediately(aw, timeout):
            if hasattr(aw, "cancel"):
                aw.cancel()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(app_worker.asyncio, "wait_for", _timeout_immediately)

        async def _dummy():
            pass

        task = asyncio.create_task(_dummy())
        broker = AsyncMock()
        ctx = {
            "alpaca": broker,
            "listeners": [],
            "listener_tasks": [task],
        }

        await app_worker.shutdown(ctx)

        capture.assert_called_once()
        message, kwargs = capture.call_args.args[0], capture.call_args.kwargs
        assert "timed out" in message
        assert kwargs["level"] == "warning"
        # Broker close must still happen even after listener shutdown timeout.
        broker.close.assert_awaited_once()

        # Clean up the orphan task so pytest is happy.
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):  # noqa: BLE001
            pass

    async def test_shutdown_swallows_broker_close_failures(self):
        """A failing broker.close must not raise out of shutdown — otherwise
        a flaky Alpaca socket teardown could wedge the worker mid-deploy."""
        broker = AsyncMock()
        broker.close.side_effect = RuntimeError("httpx client already gone")
        ctx = {"alpaca": broker, "listeners": [], "listener_tasks": []}

        # Must not raise.
        await app_worker.shutdown(ctx)
        broker.close.assert_awaited_once()

    async def test_shutdown_handles_missing_ctx_keys(self):
        """If startup errored before populating ctx, shutdown must still
        complete cleanly using `ctx.get(...)` defaults."""
        await app_worker.shutdown({})  # must not raise


class TestInstall:
    def test_install_patches_arq_worker_close(self):
        from arq import worker as arq_worker

        assert arq_worker.Worker.close is app_worker._safe_close

    def test_install_is_idempotent(self):
        from arq import worker as arq_worker

        app_worker._patch_arq_worker_close()
        app_worker._patch_arq_worker_close()
        assert arq_worker.Worker.close is app_worker._safe_close

    async def test_calling_arq_worker_close_routes_through_patch(self):
        """End-to-end: invoking Worker.close on the real arq class uses _safe_close."""
        from arq import worker as arq_worker

        fake = _FakeWorker(delete_side_effect=RedisTimeoutError("server gone"))
        await arq_worker.Worker.close(fake)
        fake.pool.delete.assert_awaited_once()
        fake.pool.close.assert_awaited_once_with(close_connection_pool=True)
        assert fake._pool is None
