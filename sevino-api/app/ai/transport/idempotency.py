"""Redis-backed idempotency for the chat-turn endpoint.

Slot at ``ai:idem:{user_id}:{idempotency_key}``:

* absent    → claim it (status=in_flight, 2-min TTL).
* in_flight → 409.
* complete  → replay the persisted response.

Crashed in-flight claims are released with ``DEL`` rather than a literal
``failed`` value — storing ``failed`` would need WATCH/MULTI/EXEC to avoid
a CAS race between post-failure claimers.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from redis.asyncio import Redis


# Outlasts the 60s wall-clock cap; short enough to self-heal after a
# process kill that skipped the try/finally.
DEFAULT_IN_FLIGHT_TTL_S = 120

# Long replay window so retries from network blips return the same
# response without re-invoking Anthropic.
DEFAULT_COMPLETE_TTL_S = 24 * 60 * 60


ClaimStatus = Literal["claimed", "in_flight", "complete"]


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    # ``turn_id`` is: the caller's own when claimed; the existing holder's
    # when in_flight (may be None if malformed); the original successful
    # run's when complete.
    status: ClaimStatus
    turn_id: uuid.UUID | None


# Scoped per-user so two users can submit the same key without colliding
# and a leaked key can't pin another account's slot.
def _redis_key(*, user_id: uuid.UUID, idempotency_key: str) -> str:
    return f"ai:idem:{user_id}:{idempotency_key}"


def _parse_turn_id(raw: object) -> uuid.UUID | None:
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def claim_idempotency(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    idempotency_key: str,
    turn_id: uuid.UUID,
    in_flight_ttl_s: int = DEFAULT_IN_FLIGHT_TTL_S,
) -> IdempotencyClaim:
    """Claim the slot for ``(user_id, idempotency_key)``.

    First claim wins via ``SET ... NX``.
    """
    redis_key = _redis_key(user_id=user_id, idempotency_key=idempotency_key)
    in_flight_payload = json.dumps({
        "status": "in_flight",
        "turn_id": str(turn_id),
        "started_at": time.time(),
    })

    # redis-py returns ``None`` (not ``False``) on a failed SET NX.
    won = await redis.set(
        redis_key, in_flight_payload, nx=True, ex=in_flight_ttl_s
    )
    if won:
        return IdempotencyClaim(status="claimed", turn_id=turn_id)

    raw = await redis.get(redis_key)
    if raw is None:
        # Existing record TTLed out between SET NX and GET. Retry once;
        # treat a second miss as ``claimed`` rather than spinning.
        won = await redis.set(
            redis_key, in_flight_payload, nx=True, ex=in_flight_ttl_s
        )
        if won:
            return IdempotencyClaim(status="claimed", turn_id=turn_id)
        raw = await redis.get(redis_key)
        if raw is None:
            return IdempotencyClaim(status="claimed", turn_id=turn_id)

    record = json.loads(raw)
    record_status = record.get("status")

    if record_status == "complete":
        return IdempotencyClaim(
            status="complete",
            turn_id=_parse_turn_id(record.get("turn_id")),
        )

    # Unrecognised values fall through to in_flight: better to 409 than
    # to double-run.
    return IdempotencyClaim(
        status="in_flight",
        turn_id=_parse_turn_id(record.get("turn_id")),
    )


async def mark_complete(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    idempotency_key: str,
    turn_id: uuid.UUID,
    complete_ttl_s: int = DEFAULT_COMPLETE_TTL_S,
) -> None:
    """Flip the slot to ``complete`` so retries replay instead of
    re-invoking Anthropic. Persist the assistant message first.
    """
    redis_key = _redis_key(user_id=user_id, idempotency_key=idempotency_key)
    payload = json.dumps({
        "status": "complete",
        "turn_id": str(turn_id),
        "completed_at": time.time(),
    })
    await redis.set(redis_key, payload, ex=complete_ttl_s)


async def mark_failed(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    idempotency_key: str,
) -> None:
    """Release the slot so retries aren't blocked for the full TTL."""
    redis_key = _redis_key(user_id=user_id, idempotency_key=idempotency_key)
    await redis.delete(redis_key)


async def get_idempotency_redis(request: Request) -> Redis:
    # ``ArqRedis`` subclasses ``redis.asyncio.Redis``.
    return request.app.state.arq
