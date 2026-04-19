import asyncio
import signal

import sentry_sdk
import structlog
from arq import worker as arq_worker
from arq.cron import cron

from app.config import get_redis_settings, settings
from app.logging_config import configure_logging
from app.tasks.health_ping import health_ping

configure_logging(settings.environment)
logger = structlog.get_logger(__name__)


# On Railway, Redis is already gone by the time arq runs `Worker.close()`
# (SIGTERM during deploys/restarts/scale-downs races the upstream socket
# close). The two cleanup calls below fail predictably and aren't
# actionable; everything else inside `close()` is still allowed to raise
# so real errors (cancelled tasks, on_shutdown hook failures) stay visible.
_SHUTDOWN_CLEANUP_ERRORS = (
    TimeoutError,
    ConnectionError,
    asyncio.CancelledError,
)


async def _safe_close(self: arq_worker.Worker) -> None:
    if not self._handle_signals:
        self.handle_sig(signal.SIGUSR1)
    if not self._pool:
        return
    await asyncio.gather(*self.tasks.values())
    try:
        await self.pool.delete(self.health_check_key)
    except _SHUTDOWN_CLEANUP_ERRORS as exc:
        logger.info(
            "arq_health_check_cleanup_skipped",
            exc_type=type(exc).__name__,
            error=str(exc),
        )
    if self.on_shutdown:
        await self.on_shutdown(self.ctx)
    try:
        await self.pool.close(close_connection_pool=True)
    except _SHUTDOWN_CLEANUP_ERRORS as exc:
        logger.info(
            "arq_pool_close_skipped",
            exc_type=type(exc).__name__,
            error=str(exc),
        )
    self._pool = None


arq_worker.Worker.close = _safe_close


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
