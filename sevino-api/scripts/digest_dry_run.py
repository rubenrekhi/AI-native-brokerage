"""Run Daily Digest generation for a user without persisting a snapshot.

Run:
    uv run python scripts/digest_dry_run.py --user-email user@example.com

Requires local infrastructure and real provider keys in `.env`. The script
prints only the ordered digest cards as JSON to stdout so it can be piped to
`jq`; progress/errors go to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.anthropic_client import create_anthropic_client
from app.config import settings
from app.database import async_session
from app.logging_config import configure_logging
from app.models.user_profile import UserProfile
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.digest.service import DigestService
from app.services.fmp import FmpClient
from app.services.market_data import build_market_data_service


async def _user_id_for_email(email: str) -> uuid.UUID:
    async with async_session() as db:
        result = await db.execute(
            select(UserProfile.id).where(UserProfile.email == email)
        )
        user_id = result.scalar_one_or_none()
        if user_id is None:
            raise RuntimeError(f"No user_profile found for {email!r}")
        return user_id


async def _run(user_email: str) -> list[dict]:
    if not settings.fmp_api_key:
        raise RuntimeError("FMP_API_KEY is required for digest dry-run")
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for digest dry-run")

    user_id = await _user_id_for_email(user_email)
    alpaca = AlpacaBrokerService()
    fmp = FmpClient(api_key=settings.fmp_api_key)
    redis = Redis.from_url(settings.market_data_redis_url)
    market_data = build_market_data_service(
        fmp=fmp,
        alpaca_broker=alpaca,
        redis=redis,
    )
    anthropic = create_anthropic_client()
    try:
        async with async_session() as db:
            service = DigestService(
                db,
                alpaca=alpaca,
                market_data=market_data,
                fmp=fmp,
                anthropic=anthropic,
            )
            snapshot = await service.preview_for_user(user_id)
            await db.rollback()
            return snapshot.cards
    finally:
        await market_data.close()
        await redis.aclose()
        await anthropic.close()
        await alpaca.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    configure_logging(settings.environment)
    try:
        cards = asyncio.run(_run(args.user_email))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(cards, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
