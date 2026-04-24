import os
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
    railway_env = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    if railway_env.startswith("pr-"):
        logger.debug("listener_liveness_skipped_pr_preview", railway_env=railway_env)
        return {"checked": 0, "silent": 0, "skipped": "pr-preview"}

    listeners = ctx.get("listeners") or []
    now = time.monotonic()
    silent: list[dict] = []

    for listener in listeners:
        silence = now - listener.last_message_received_at
        if silence > listener.silence_threshold_seconds:
            silence_seconds = round(silence)
            silent.append(
                {
                    "stream": listener.stream_name,
                    "silence_seconds": silence_seconds,
                    "threshold_seconds": listener.silence_threshold_seconds,
                }
            )
            # Fresh scope per listener so tags don't leak between alerts and
            # ops can filter "show only trade_events_ws silence alerts" via
            # the sse_stream tag.
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("sse_stream", listener.stream_name)
                scope.set_tag("alert_type", "sse_silence")
                if railway_env:
                    scope.set_tag("railway_environment", railway_env)
                scope.set_context(
                    "sse_silence",
                    {
                        "stream": listener.stream_name,
                        "silence_seconds": silence_seconds,
                        "threshold_seconds": listener.silence_threshold_seconds,
                    },
                )
                sentry_sdk.capture_message(
                    f"SSE listener '{listener.stream_name}' silent for "
                    f"{silence_seconds}s (threshold "
                    f"{listener.silence_threshold_seconds}s)",
                    level="warning",
                )

    if silent:
        logger.warning("listener_liveness_silent", silent=silent)
    else:
        logger.info("listener_liveness_ok", count=len(listeners))

    return {"checked": len(listeners), "silent": len(silent)}
