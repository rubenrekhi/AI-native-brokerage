"""Business logic for the Daily Digest.

`generate_for_user` runs the (currently empty) generator set, persists the
result, and is what the morning cron (T12) will call per user.
`get_today` / `dismiss` back the two `/v1/digest` endpoints. Generators,
the heuristic shortlist, and the Anthropic reranker land in later tickets
(T7–T11) — until then `generate_for_user` ships an empty card stack
end-to-end so the type contracts and persistence are settled.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.digest import DigestSnapshot
from app.repositories.digest import DigestRepository
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.context import ET, build_context
from app.services.digest.types import CardCandidate, DigestContext, Generator

logger = structlog.get_logger(__name__)


class DigestService:
    """Generate, read, and dismiss a user's daily digest.

    `alpaca` is only needed by `generate_for_user` (via `build_context`);
    the read/dismiss paths run with `alpaca=None`, which is why the
    `/v1/digest` route constructs the service without it.
    """

    def __init__(
        self,
        db: AsyncSession,
        alpaca: AlpacaBrokerService | None = None,
        generators: list[Generator] | None = None,
    ) -> None:
        self._db = db
        self._alpaca = alpaca
        self._generators: list[Generator] = (
            list(generators) if generators is not None else []
        )

    async def generate_for_user(self, user_id: uuid.UUID) -> DigestSnapshot:
        """Build context, run generators, and upsert today's snapshot.

        Idempotent per `(user_id, ny_local_date)`: re-running refreshes the
        cards in place (see `DigestRepository.upsert`).
        """
        if self._alpaca is None:
            raise RuntimeError("generate_for_user requires an Alpaca client")

        now = datetime.now(timezone.utc)
        ctx = await build_context(user_id, self._db, self._alpaca)
        candidates = await self._gather_candidates(ctx)
        cards = [candidate.card for candidate in candidates]

        snapshot = DigestSnapshot(
            user_id=user_id,
            ny_local_date=now.astimezone(ET).date(),
            cards=[card.model_dump(mode="json") for card in cards],
            generated_at=now,
        )
        persisted = await DigestRepository.upsert(self._db, snapshot)
        logger.info(
            "digest_generated",
            user_id=str(user_id),
            card_count=len(cards),
            ny_local_date=persisted.ny_local_date.isoformat(),
        )
        return persisted

    async def get_today(
        self, user_id: uuid.UUID
    ) -> DigestSnapshot | None:
        """Today's (NY-local) digest, dismissed or not. None when absent."""
        return await DigestRepository.get_by_user_and_date(
            self._db, user_id, _today()
        )

    async def dismiss(self, user_id: uuid.UUID) -> DigestSnapshot:
        """Mark today's digest dismissed. 404 if there's nothing to dismiss."""
        snapshot = await DigestRepository.get_by_user_and_date(
            self._db, user_id, _today()
        )
        if snapshot is None:
            raise NotFoundError("No digest to dismiss")
        dismissed = await DigestRepository.mark_dismissed(
            self._db, snapshot.id
        )
        if dismissed is None:
            raise NotFoundError("No digest to dismiss")
        return dismissed

    async def _gather_candidates(
        self, ctx: DigestContext
    ) -> list[CardCandidate]:
        if not self._generators:
            return []
        results = await asyncio.gather(
            *(generator.generate(ctx) for generator in self._generators)
        )
        return [candidate for batch in results for candidate in batch]


def _today():
    return datetime.now(timezone.utc).astimezone(ET).date()
