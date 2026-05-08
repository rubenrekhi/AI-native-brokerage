"""Redis-backed idempotency for the chat-turn endpoint.

Per AI v0 plan B3.1 (sevino-api/docs/ai-v0-plan.md). Function-style helpers
that the route handler calls at well-defined points in its own lifecycle —
deliberately *not* a Starlette ``BaseHTTPMiddleware``. The chat-turn endpoint
needs surgical control over the state transitions: claim before
``run_agent_turn`` opens its DB session, mark complete only after the
assistant message is durably persisted, mark failed in ``try/finally`` on
any crash so retries aren't blocked for the full TTL window. A wrapping
middleware can't see those boundaries.

State machine for the value at key ``ai:idem:{user_id}:{idempotency_key}``:

* absent      → :func:`claim_idempotency` returns ``claimed`` and writes
                ``{status: "in_flight", turn_id, started_at}`` with a
                2-minute TTL.
* in_flight   → :func:`claim_idempotency` returns ``in_flight``; the route
                should respond 409 (a parallel client is still running the
                same key).
* complete    → :func:`claim_idempotency` returns ``complete`` with the
                original ``turn_id``; the route should replay the persisted
                response (B3.2 / SEV-487 wires that path in).

The fourth transition — ``in_flight`` back to a re-claimable slot after a
crash — is implemented by :func:`mark_failed` as a ``DEL``, not a separate
``status: "failed"`` value. The route handler's only question on retry is
"is the slot taken?", which absence answers cleanly. Storing a literal
``failed`` value would re-introduce a CAS race between concurrent
post-failure claimers (each would read ``failed`` and both would believe
they overwrote it with their own ``in_flight``), and resolving that race
would require either a Lua script or WATCH/MULTI/EXEC — heavyweight for a
state that exists only to unblock retries.

Redis is already configured (slowapi + ARQ both share the same instance);
no new infra. Production routes pull the client from ``app.state.arq``
(an ``arq.ArqRedis`` which subclasses ``redis.asyncio.Redis``) via
:func:`get_idempotency_redis`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from redis.asyncio import Redis


# Long enough to outlast the longest legitimate Anthropic turn (D11 caps the
# wall clock at 60s) with margin for FastAPI / network overhead, short
# enough that a stuck slot from a process kill (where the try/finally never
# runs) self-heals within a couple of minutes.
DEFAULT_IN_FLIGHT_TTL_S = 120

# Replay records live longer so legitimately retried submissions (network
# blips, app backgrounding, the iOS retry policy) keep returning the same
# response without re-invoking Anthropic. The assistant message itself is
# durably persisted in Postgres; this Redis record is just the gate that
# lets the route skip the model call.
DEFAULT_COMPLETE_TTL_S = 24 * 60 * 60


ClaimStatus = Literal["claimed", "in_flight", "complete"]


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """Outcome of :func:`claim_idempotency`.

    ``turn_id`` semantics depend on ``status``:

    * ``claimed``   — the caller's own ``turn_id`` is echoed back; the route
                      proceeds to run the turn.
    * ``in_flight`` — the ``turn_id`` of the request that already holds the
                      slot (useful for logs / 409 detail). May be ``None``
                      if the existing record is malformed.
    * ``complete``  — the ``turn_id`` of the original successful run; the
                      route uses this to load the persisted assistant
                      message for replay.
    """

    status: ClaimStatus
    turn_id: uuid.UUID | None


# User-scope keys so two users can submit the same idempotency string
# without colliding, and so a leaked key from one account can't pin
# another account's slot.
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
    """Attempt to claim the idempotency slot for ``(user_id, idempotency_key)``.

    Atomicity for the "first claim wins" guarantee comes from Redis ``SET
    ... NX``: at most one of N concurrent claimers can SET the absent key,
    and the rest fall through to the classification path. The fast path is
    a single round-trip in the uncontested case (which is the common case).
    """
    redis_key = _redis_key(user_id=user_id, idempotency_key=idempotency_key)
    in_flight_payload = json.dumps({
        "status": "in_flight",
        "turn_id": str(turn_id),
        "started_at": time.time(),
    })

    # SET NX returns True if it set the key, None if a value already
    # existed. (redis-py uses None rather than False for the "didn't set"
    # branch — ``if won`` correctly distinguishes both.)
    won = await redis.set(
        redis_key, in_flight_payload, nx=True, ex=in_flight_ttl_s
    )
    if won:
        return IdempotencyClaim(status="claimed", turn_id=turn_id)

    # SET NX failed — somebody else is in the slot, or just finished it.
    raw = await redis.get(redis_key)
    if raw is None:
        # Rare: the existing record TTLed out between the SET NX and the
        # GET. Retry the SET NX once. If we still lose, classify whatever
        # is now there. Two consecutive races here would mean very high
        # contention on a key whose TTL is also expiring, which is
        # extraordinarily unlikely in practice; we treat the third miss as
        # ``claimed`` rather than spinning.
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

    # Anything else (the documented ``in_flight`` value, or a future value
    # we don't recognize) is treated as ``in_flight``: better to 409 a
    # potentially-still-running request than to double-run a turn.
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
    """Promote the slot to ``complete`` so subsequent claims with the same
    key take the replay path instead of re-invoking Anthropic.

    The caller is responsible for persisting the assistant message to
    Postgres before invoking this — once the slot flips to ``complete``, a
    replaying retry will look up that message by ``turn_id``.
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
    """Release the slot after a crash so retries aren't blocked for the
    full in-flight TTL.

    Implemented as ``DEL``: the route's only question on retry is "is the
    slot taken?", which absence answers cleanly. See module docstring for
    why a literal ``status: "failed"`` value isn't worth the CAS race it
    would create.
    """
    redis_key = _redis_key(user_id=user_id, idempotency_key=idempotency_key)
    await redis.delete(redis_key)


async def get_idempotency_redis(request: Request) -> Redis:
    """FastAPI dependency that yields the shared Redis client.

    Reuses the ARQ pool on ``app.state.arq`` — ``ArqRedis`` is a subclass
    of ``redis.asyncio.Redis``, so the SET/GET/DEL surface this module
    needs is available without standing up a second connection pool.
    """
    return request.app.state.arq
