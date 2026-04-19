import asyncio
import signal
import time

import sentry_sdk
import structlog
from arq import worker as arq_worker
from arq.cron import cron
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import get_redis_settings, settings
from app.logging_config import configure_logging
from app.tasks.health_ping import health_ping

logger = structlog.get_logger(__name__)


# On Railway, Redis is already gone by the time arq runs `Worker.close()`
# (SIGTERM during deploys/restarts/scale-downs races the upstream socket
# close). The two cleanup calls we wrap below fail predictably and aren't
# actionable; everything else inside `close()` is still allowed to raise
# so real errors (cancelled tasks, on_shutdown hook failures) stay visible.
#
# redis-py defines its own ConnectionError/TimeoutError that inherit from
# RedisError(Exception) — NOT from the builtins — so we must catch both
# variants explicitly. The builtin TimeoutError also covers
# asyncio.TimeoutError (aliased since Py3.11).
#
# asyncio.CancelledError is NOT swallowed — it means the event loop itself
# is asking the coroutine to stop, and silently catching it can cause the
# outer supervisor (tests, timeouts, arq's signal handler) to hang.
_SHUTDOWN_CLEANUP_ERRORS = (
    TimeoutError,
    ConnectionError,
    RedisTimeoutError,
    RedisConnectionError,
)


async def _safe_close(self: arq_worker.Worker) -> None:
    # Mirrors arq 0.27.0 Worker.close (worker.py:864-874). Re-verify on arq upgrade.
    if not self._handle_signals:
        self.handle_sig(signal.SIGUSR1)
    if not self._pool:
        return
    await asyncio.gather(*self.tasks.values())

    start = time.perf_counter()
    try:
        await self.pool.delete(self.health_check_key)
    except asyncio.CancelledError:
        logger.warning(
            "arq_health_check_cleanup_cancelled",
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        raise
    except _SHUTDOWN_CLEANUP_ERRORS as exc:
        logger.warning(
            "arq_health_check_cleanup_skipped",
            exc_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    if self.on_shutdown:
        await self.on_shutdown(self.ctx)

    start = time.perf_counter()
    try:
        await self.pool.close(close_connection_pool=True)
    except asyncio.CancelledError:
        logger.warning(
            "arq_pool_close_cancelled",
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        raise
    except _SHUTDOWN_CLEANUP_ERRORS as exc:
        logger.warning(
            "arq_pool_close_skipped",
            exc_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
    self._pool = None


def _install() -> None:
    """Wire logging + patch arq.Worker.close. Idempotent."""
    configure_logging(settings.environment)
    arq_worker.Worker.close = _safe_close  # type: ignore[assignment]


_install()


async def startup(ctx: dict) -> None:
    """Called when the worker starts. Initialize shared resources."""
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1,
        )
        sentry_sdk.set_tag("process", "worker")


async def shutdown(ctx: dict) -> None:
    """Called when the worker shuts down. Clean up shared resources."""
    pass


class WorkerSettings:
    functions = [health_ping]
    cron_jobs = [cron(health_ping, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
