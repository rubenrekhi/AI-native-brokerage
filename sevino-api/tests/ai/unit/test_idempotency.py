"""Unit tests for the chat-turn idempotency helpers.

Per AI v0 plan B3.1 acceptance criteria (sevino-api/docs/ai-v0-plan.md):

* Two parallel claims with the same key — first runs, second 409s.
* After the first completes, a third claim with the same key returns the
  complete marker.
* A crashed ``try/finally`` correctly transitions ``in_flight`` → freed
  within the TTL window so a retry can proceed.

Tests use ``fakeredis.aioredis.FakeRedis`` which implements the same
``redis.asyncio.Redis`` surface ``app/ai/transport/idempotency.py`` calls.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from app.ai.transport.idempotency import (
    DEFAULT_IN_FLIGHT_TTL_S,
    IdempotencyClaim,
    claim_idempotency,
    mark_complete,
    mark_failed,
)


@pytest.fixture
async def redis():
    client = FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def idempotency_key() -> str:
    return "client-key-1"


class TestClaim:
    async def test_first_claim_returns_claimed(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        turn_id = uuid.uuid4()

        result = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
        )

        assert result == IdempotencyClaim(status="claimed", turn_id=turn_id)

    async def test_first_claim_writes_in_flight_record_with_started_at(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        turn_id = uuid.uuid4()

        await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
        )

        raw = await redis.get(f"ai:idem:{user_id}:{idempotency_key}")
        record = json.loads(raw)
        assert record["status"] == "in_flight"
        assert record["turn_id"] == str(turn_id)
        assert isinstance(record["started_at"], (int, float))

    async def test_first_claim_sets_2_minute_ttl(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        ttl = await redis.ttl(f"ai:idem:{user_id}:{idempotency_key}")
        # fakeredis returns the configured TTL exactly; production would
        # return up to N-1 seconds depending on rounding, so allow a small
        # window for both.
        assert DEFAULT_IN_FLIGHT_TTL_S - 5 <= ttl <= DEFAULT_IN_FLIGHT_TTL_S

    async def test_parallel_claims_first_wins_second_is_in_flight(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Acceptance: two parallel requests with same key — first runs,
        # second 409s.
        turn_a = uuid.uuid4()
        turn_b = uuid.uuid4()

        results = await asyncio.gather(
            claim_idempotency(
                redis,
                user_id=user_id,
                idempotency_key=idempotency_key,
                turn_id=turn_a,
            ),
            claim_idempotency(
                redis,
                user_id=user_id,
                idempotency_key=idempotency_key,
                turn_id=turn_b,
            ),
        )

        statuses = sorted(r.status for r in results)
        assert statuses == ["claimed", "in_flight"]
        winner = next(r for r in results if r.status == "claimed")
        loser = next(r for r in results if r.status == "in_flight")
        assert winner.turn_id in {turn_a, turn_b}
        # The 409 path tells the caller which turn already owns the slot.
        assert loser.turn_id == winner.turn_id

    async def test_burst_of_claims_only_one_wins(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Stronger version of the parallel test: under a burst of 10
        # concurrent claimers, exactly one wins and the rest see in_flight.
        turns = [uuid.uuid4() for _ in range(10)]

        results = await asyncio.gather(
            *(
                claim_idempotency(
                    redis,
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    turn_id=t,
                )
                for t in turns
            )
        )

        claimed = [r for r in results if r.status == "claimed"]
        in_flight = [r for r in results if r.status == "in_flight"]
        assert len(claimed) == 1
        assert len(in_flight) == 9

    async def test_in_flight_returns_owner_turn_id(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        owner = uuid.uuid4()
        await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=owner,
        )

        retry = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        assert retry.status == "in_flight"
        assert retry.turn_id == owner

    async def test_user_scoping_isolates_collisions(
        self, redis: FakeRedis, idempotency_key: str
    ) -> None:
        # Two users submitting the same idempotency string must each get
        # their own slot — keys are scoped by user_id.
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        a = await claim_idempotency(
            redis,
            user_id=user_a,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )
        b = await claim_idempotency(
            redis,
            user_id=user_b,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        assert a.status == "claimed"
        assert b.status == "claimed"

    async def test_malformed_record_classified_as_in_flight(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Defensive: an unrecognized status (corrupted record, future
        # schema) defaults to in_flight so the route 409s rather than
        # double-running a turn.
        key = f"ai:idem:{user_id}:{idempotency_key}"
        await redis.set(
            key, json.dumps({"status": "weird", "turn_id": str(uuid.uuid4())})
        )

        result = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        assert result.status == "in_flight"

    async def test_record_with_invalid_turn_id_returns_none(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        key = f"ai:idem:{user_id}:{idempotency_key}"
        await redis.set(
            key, json.dumps({"status": "in_flight", "turn_id": "not-a-uuid"})
        )

        result = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        assert result.status == "in_flight"
        assert result.turn_id is None

    async def test_double_ttl_race_falls_through_to_claimed(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Cover the recovery branch where SET NX loses, the subsequent GET
        # finds the record TTLed-out, the retry SET NX *also* loses, and
        # the second GET still sees nothing. fakeredis can't naturally
        # produce this state, so monkeypatch the two calls to simulate it.
        # The contract under this much contention is "claim and proceed
        # rather than spin", so the result must be ``claimed``.
        turn_id = uuid.uuid4()

        async def always_lose_set(*args, **kwargs):
            return None

        async def always_miss_get(*args, **kwargs):
            return None

        redis.set = always_lose_set  # type: ignore[method-assign]
        redis.get = always_miss_get  # type: ignore[method-assign]

        result = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
        )

        assert result == IdempotencyClaim(status="claimed", turn_id=turn_id)


class TestMarkComplete:
    async def test_complete_lets_subsequent_claim_replay(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Acceptance: after first completes, third request with same key
        # returns the complete marker.
        first_turn = uuid.uuid4()

        first = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=first_turn,
        )
        assert first.status == "claimed"

        await mark_complete(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=first_turn,
        )

        retry = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )

        assert retry.status == "complete"
        assert retry.turn_id == first_turn

    async def test_complete_record_uses_long_ttl(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )
        turn_id = uuid.uuid4()
        await mark_complete(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
        )

        ttl = await redis.ttl(f"ai:idem:{user_id}:{idempotency_key}")
        # Replay TTL is 24h; just assert it's well above the 2-min
        # in-flight TTL so a retry an hour later still replays.
        assert ttl > DEFAULT_IN_FLIGHT_TTL_S * 10


class TestMarkFailed:
    async def test_failed_unblocks_retry_within_ttl_window(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Acceptance: crashed try/finally transitions in_flight → failed
        # within the TTL window. The observable contract is "a retry with
        # the same key after mark_failed succeeds (gets ``claimed``)
        # rather than seeing in_flight 409 for the full 2-minute TTL."
        first_turn = uuid.uuid4()
        first = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=first_turn,
        )
        assert first.status == "claimed"

        # Verify the slot is currently visible as in_flight to a parallel
        # claimer — establishes that we're testing the released-from-
        # in_flight path, not the released-from-absent path.
        contender = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )
        assert contender.status == "in_flight"
        assert contender.turn_id == first_turn

        # Crash path: route handler's try/finally calls mark_failed.
        await mark_failed(
            redis, user_id=user_id, idempotency_key=idempotency_key
        )

        # Retry can claim the slot.
        second_turn = uuid.uuid4()
        retry = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=second_turn,
        )
        assert retry == IdempotencyClaim(status="claimed", turn_id=second_turn)

    async def test_mark_failed_is_idempotent_for_absent_key(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Defensive: route's finally block must not raise if the slot was
        # already cleared (e.g. the in_flight TTL elapsed before the
        # crash handler ran).
        await mark_failed(
            redis, user_id=user_id, idempotency_key=idempotency_key
        )  # no key present — DEL returns 0, no exception

    async def test_mark_failed_after_complete_clears_replay_record(
        self, redis: FakeRedis, user_id: uuid.UUID, idempotency_key: str
    ) -> None:
        # Not strictly required by the acceptance criteria, but documents
        # the behavior: mark_failed unconditionally drops the record,
        # including a complete one. The route handler shouldn't ever call
        # mark_failed after mark_complete, but if it did (a buggy
        # try/finally), the next claim runs the turn fresh rather than
        # serving a replay tied to a now-orphaned record.
        first_turn = uuid.uuid4()
        await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=first_turn,
        )
        await mark_complete(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=first_turn,
        )
        await mark_failed(
            redis, user_id=user_id, idempotency_key=idempotency_key
        )

        retry = await claim_idempotency(
            redis,
            user_id=user_id,
            idempotency_key=idempotency_key,
            turn_id=uuid.uuid4(),
        )
        assert retry.status == "claimed"
