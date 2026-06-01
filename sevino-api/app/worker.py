import asyncio
import logging
import signal
import time

import redis.asyncio as aioredis
import sentry_sdk
import structlog
from arq import func
from arq import worker as arq_worker
from arq.cron import cron
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.ai.anthropic_client import create_anthropic_client
from app.config import get_redis_settings, settings
from app.sentry_config import before_send as sentry_before_send
from app.listeners.registry import build_listeners
from app.logging_config import configure_logging
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.fmp import FmpClient
from app.services.market_data import MarketDataService, build_market_data_service
from app.tasks.cash_interest import (
    ENROLL_CASH_INTEREST_MAX_TRIES,
    enroll_cash_interest,
)
from app.tasks.generate_daily_digest import generate_daily_digest
from app.tasks.generate_radar_batch import generate_radar_batch
from app.tasks.health_ping import health_ping
from app.tasks.listener_liveness import check_listener_liveness
from app.tasks.reconcile_funding import reconcile_funding
from app.tasks.refresh_due_radar import refresh_due_radar
from app.tasks.sweep_digest_snapshots import sweep_digest_snapshots
from app.tasks.sweep_expired_radar import sweep_expired_radar_items
from app.tasks.sync_assets import sync_assets

logger = structlog.get_logger(__name__)


# Max seconds we'll wait for all listener tasks to exit after their
# cancellation is requested. Railway's SIGTERM → SIGKILL window is ~30s in
# practice, so keep this well under that.
_LISTENER_SHUTDOWN_TIMEOUT_SECONDS = 10.0


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
SHUTDOWN_CLEANUP_ERRORS = (
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
    except SHUTDOWN_CLEANUP_ERRORS as exc:
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
    except SHUTDOWN_CLEANUP_ERRORS as exc:
        logger.warning(
            "arq_pool_close_skipped",
            exc_type=type(exc).__name__,
            error=str(exc),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
    self._pool = None


def _configure_worker_logging() -> None:
    """Wire structlog for the worker process. Idempotent."""
    configure_logging(settings.environment)


def _patch_arq_worker_close() -> None:
    """Replace arq.Worker.close with _safe_close. Idempotent."""
    arq_worker.Worker.close = _safe_close  # type: ignore[assignment]


_configure_worker_logging()
_patch_arq_worker_close()


async def startup(ctx: dict) -> None:
    """Called when the worker starts. Initialize shared resources and spawn
    long-running listener tasks."""
    # arq's CLI applies `default_log_config(...)` between module import and
    # this hook, which installs its own handler on the 'arq' logger. Combined
    # with our root handler (set by configure_logging), every arq log record
    # prints twice — once in arq's "HH:MM:SS: msg" format, once in ours.
    # Clear arq's handlers so its logs propagate up to our root structlog
    # formatter only.
    logging.getLogger("arq").handlers.clear()

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=0.1,
            before_send=sentry_before_send,
        )
        sentry_sdk.set_tag("process", "worker")

    broker = AlpacaBrokerService()
    # Separate client from ARQ's pool: cache reads/writes assume
    # decode_responses=True (strings, not bytes), and the listener's
    # lifecycle is independent of the job-queue connection.
    cache_redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        encoding="utf-8",
    )
    # ctx["redis"] is the ArqRedis pool the worker started with — the
    # AccountStatusListener enqueues the FDIC sweep enrollment task onto it
    # when an account first goes ACTIVE (SEV-655).
    listeners = build_listeners(broker, redis=cache_redis, arq=ctx.get("redis"))
    listener_tasks = [
        asyncio.create_task(listener.run(), name=f"sse-{listener.stream_name}")
        for listener in listeners
    ]

    ctx["alpaca"] = broker
    ctx["cache_redis"] = cache_redis
    ctx["listeners"] = listeners
    ctx["listener_tasks"] = listener_tasks
    ctx["anthropic"] = create_anthropic_client()
    # sync_assets enriches the catalog from FMP only when this client is
    # present. Skip when no key is configured (e.g. dev) so the rest of the
    # worker still boots.
    ctx["fmp"] = FmpClient(api_key=settings.fmp_api_key) if settings.fmp_api_key else None
    if ctx["fmp"] is not None:
        market_data_redis = aioredis.from_url(settings.market_data_redis_url)
        ctx["market_data_redis"] = market_data_redis
        ctx["market_data"] = build_market_data_service(
            fmp=ctx["fmp"],
            alpaca_broker=broker,
            redis=market_data_redis,
        )
    else:
        ctx["market_data_redis"] = None
        ctx["market_data"] = None

    logger.info("worker_listeners_started", count=len(listeners))


async def shutdown(ctx: dict) -> None:
    """Called when the worker shuts down. Cancel listeners, close shared
    resources. Cleanup failures are logged but never re-raised — we don't
    want shutdown to hang on a stuck listener."""
    listener_tasks: list[asyncio.Task] = ctx.get("listener_tasks", [])
    for task in listener_tasks:
        task.cancel()
    if listener_tasks:
        # Bounded wait so a handler that's ignoring cancellation (stuck DB
        # transaction, slow Alpaca REST call, etc.) doesn't hang the whole
        # worker shutdown and block a Railway redeploy.
        try:
            await asyncio.wait_for(
                asyncio.gather(*listener_tasks, return_exceptions=True),
                timeout=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS,
            )
            logger.info("worker_listeners_stopped", count=len(listener_tasks))
        except asyncio.TimeoutError:
            logger.warning(
                "worker_listeners_shutdown_timeout",
                count=len(listener_tasks),
                timeout_seconds=_LISTENER_SHUTDOWN_TIMEOUT_SECONDS,
            )
            # Operationally notable: a listener ignored cancellation and the
            # worker had to walk away. Capture as a Sentry alert so it's
            # visible without digging through Railway logs.
            sentry_sdk.capture_message(
                f"Worker shutdown timed out waiting for {len(listener_tasks)} "
                f"listener(s) to stop (timeout: "
                f"{_LISTENER_SHUTDOWN_TIMEOUT_SECONDS}s)",
                level="warning",
            )

    broker: AlpacaBrokerService | None = ctx.get("alpaca")
    if broker is not None:
        try:
            await broker.close()
        except Exception as exc:
            logger.warning("worker_alpaca_close_failed", error=str(exc))

    fmp: FmpClient | None = ctx.get("fmp")
    market_data: MarketDataService | None = ctx.get("market_data")
    if market_data is not None:
        try:
            await market_data.close()
        except Exception as exc:
            logger.warning("worker_market_data_close_failed", error=str(exc))
    elif fmp is not None:
        try:
            await fmp.close()
        except Exception as exc:
            logger.warning("worker_fmp_close_failed", error=str(exc))

    anthropic = ctx.get("anthropic")
    if anthropic is not None:
        try:
            await anthropic.close()
        except Exception as exc:
            logger.warning("worker_anthropic_close_failed", error=str(exc))

    cache_redis: aioredis.Redis | None = ctx.get("cache_redis")
    if cache_redis is not None:
        try:
            await cache_redis.aclose()
        except SHUTDOWN_CLEANUP_ERRORS as exc:
            # Railway's SIGTERM races socket teardown; predictable network
            # errors during close aren't actionable — log and move on.
            logger.warning(
                "worker_cache_redis_close_failed",
                exc_type=type(exc).__name__,
                error=str(exc),
            )

    market_data_redis: aioredis.Redis | None = ctx.get("market_data_redis")
    if market_data_redis is not None:
        try:
            await market_data_redis.aclose()
        except SHUTDOWN_CLEANUP_ERRORS as exc:
            logger.warning(
                "worker_market_data_redis_close_failed",
                exc_type=type(exc).__name__,
                error=str(exc),
            )


class WorkerSettings:
    functions = [
        health_ping,
        check_listener_liveness,
        sync_assets,
        sweep_expired_radar_items,
        reconcile_funding,
        generate_radar_batch,
        refresh_due_radar,
        generate_daily_digest,
        sweep_digest_snapshots,
        func(
            enroll_cash_interest,
            name="enroll_cash_interest",
            max_tries=ENROLL_CASH_INTEREST_MAX_TRIES,
        ),
    ]
    cron_jobs = [
        cron(health_ping, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(check_listener_liveness, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Pre-market sync: US equities open at 14:30 UTC / 9:30 AM ET.
        cron(sync_assets, hour={10}, minute={0}),
        # Low-traffic window; pure DB hygiene, can run any time of day.
        cron(sweep_expired_radar_items, hour={3}, minute={0}),
        # Hourly at :15 — offset from health_ping/listener_liveness on :00.
        cron(reconcile_funding, minute={15}),
        # Hourly at :05 — offset from health pings on :00.
        cron(refresh_due_radar, minute={5}),
        # 9am New York local in both DST states; idempotency makes one no-op.
        cron(generate_daily_digest, hour={13, 14}, minute={0}),
        # Retain one week of digest snapshots.
        cron(sweep_digest_snapshots, hour={4}, minute={0}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
