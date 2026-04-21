import time

import sentry_sdk
import structlog

logger = structlog.get_logger(__name__)


async def check_listener_liveness(ctx: dict) -> dict:
    """Every 5 minutes, check each registered listener's
    ``last_message_received_at`` against its configured silence threshold.
    Listeners that have been silent longer than the threshold get a Sentry
    ``capture_message`` (not an exception — silence may be legitimate, but
    we want visibility).

    Legitimate silence: account-status stream may go hours without events.
    Suspect silence: trade-events during market hours.

    The cron runs inside the same ``ctx`` as :func:`app.worker.startup`, so
    ``ctx["listeners"]`` is the same list populated at worker startup.
    """
    listeners = ctx.get("listeners") or []
    now = time.monotonic()
    silent: list[dict] = []

    for listener in listeners:
        silence = now - listener.last_message_received_at
        if silence > listener.silence_threshold_seconds:
            silent.append(
                {
                    "stream": listener.stream_name,
                    "silence_seconds": round(silence),
                    "threshold_seconds": listener.silence_threshold_seconds,
                }
            )
            sentry_sdk.capture_message(
                f"SSE listener '{listener.stream_name}' silent for "
                f"{round(silence)}s (threshold {listener.silence_threshold_seconds}s)",
                level="warning",
            )

    if silent:
        logger.warning("listener_liveness_silent", silent=silent)
    else:
        logger.info("listener_liveness_ok", count=len(listeners))

    return {"checked": len(listeners), "silent": len(silent)}
