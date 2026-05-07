import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
import sentry_sdk
import structlog
from fastapi import Request
from redis.asyncio import Redis

from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services._http import BODY_LOG_LIMIT, redact_bearer
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.fmp import (
    FmpClient,
    project_analyst,
    project_profile,
    project_quote,
    project_ratios,
)

logger = structlog.get_logger(__name__)


__all__ = [
    "MarketDataError",
    "MarketDataInvalidInputError",
    "MarketDataUnavailableError",
    "MarketDataUpstreamError",
    "MarketDataService",
    "get_market_data_service",
]


_CHART_PARAMS: dict[str, dict[str, Any]] = {
    "1D": {"timeframe": "5Min", "days_back": 1},
    "1W": {"timeframe": "30Min", "days_back": 7},
    "1M": {"timeframe": "1Hour", "days_back": 30},
    "3M": {"timeframe": "1Day", "days_back": 90},
    "6M": {"timeframe": "1Day", "days_back": 180},
    "1Y": {"timeframe": "1Day", "days_back": 365},
    "5Y": {"timeframe": "1Week", "days_back": 1825},
}

# Intraday timeframes get a short TTL because bars roll forward minute-by-minute;
# daily/weekly bars are stable for the rest of the session, so a 1h TTL is fine.
_INTRADAY_TIMEFRAMES = frozenset({"5Min", "30Min", "1Hour"})

_QUOTE_TTL = 15
_QUOTE_TTL_CLOSED = 1800
_FUNDAMENTALS_TTL = 43200
_CHART_TTL_INTRADAY = 60
_CHART_TTL_DAILY = 3600
_MARKET_STATUS_TTL = 60

# US equity tickers are 1–5 chars typically; class shares add `.` or `-`
# (e.g. BRK.B, BRK-B). Cap at 10 chars to bound cache-key and URL length.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_MARKET_STATUS_KEY = "market:status"


class AccessTokenProvider(Protocol):
    """Minimal contract for whatever provides Alpaca OAuth2 access tokens.

    `AlpacaBrokerService` satisfies this; tests can inject any object with
    a matching `access_token` coroutine without monkey-patching the full
    broker surface.
    """

    async def access_token(self) -> str: ...


class MarketDataService:
    """Orchestrates FMP, Alpaca Market Data, and Redis cache for the market-data API.

    The service owns its own httpx client for Alpaca data calls (the broker
    has a separate client for trading API hosts). FmpClient and the broker
    service are injected so token refresh and HTTP pools are shared rather
    than duplicated.

    Redis errors are non-fatal: a failed cache read falls through to the
    provider, a failed write is logged and swallowed.
    """

    def __init__(
        self,
        *,
        fmp: FmpClient,
        alpaca_broker: AccessTokenProvider,
        redis: Redis,
        alpaca_data_url: str,
        alpaca_broker_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._fmp = fmp
        self._alpaca_broker = alpaca_broker
        self._alpaca_client = client or httpx.AsyncClient(timeout=30.0)
        self._alpaca_data_url = alpaca_data_url
        self._alpaca_broker_url = alpaca_broker_url
        self._redis = redis

    async def close(self) -> None:
        await self._fmp.close()
        await self._alpaca_client.aclose()

    # ── Public API ─────────────────────────────────────────

    async def get_stock_info(self, symbol: str) -> dict[str, Any]:
        symbol = _normalize_symbol(symbol)
        quote, fundamentals, analyst = await asyncio.gather(
            self._get_quote_cached(symbol),
            self._get_fundamentals_cached(symbol),
            self._get_analyst_cached(symbol),
        )
        return {
            "quote": quote,
            "profile": fundamentals["profile"],
            "ratios": fundamentals["ratios"],
            "analyst": analyst,
        }

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, Any]:
        normalized = [_normalize_symbol(s) for s in symbols]
        cached: dict[str, dict[str, Any]] = {}
        misses: list[str] = []
        for symbol in normalized:
            hit = await self._cache_get(f"market:quote:{symbol}")
            if hit is not None:
                cached[symbol] = hit
            else:
                misses.append(symbol)

        if misses:
            raw_quotes = await self._fmp.batch_quote(misses)
            logger.info(
                "market_data_batch_quote_fetched",
                requested=len(misses),
                returned=len(raw_quotes),
            )
            ttl = await self._quote_ttl()
            for raw in raw_quotes:
                projected = project_quote(raw)
                key = projected.get("symbol")
                if not key:
                    continue
                cached[key] = projected
                await self._cache_set(f"market:quote:{key}", projected, ttl)

        return {"quotes": [cached[s] for s in normalized if s in cached]}

    async def get_chart(self, symbol: str, timeframe: str) -> dict[str, Any]:
        symbol = _normalize_symbol(symbol)
        params = _CHART_PARAMS.get(timeframe)
        if params is None:
            raise MarketDataInvalidInputError(
                f"Unsupported timeframe: {timeframe}", symbol=symbol
            )

        cache_key = f"market:chart:{symbol}:{timeframe}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        bars = await self._alpaca_bars(
            symbol, params["timeframe"], params["days_back"]
        )
        response = {"symbol": symbol, "timeframe": timeframe, "bars": bars}
        ttl = (
            _CHART_TTL_INTRADAY
            if params["timeframe"] in _INTRADAY_TIMEFRAMES
            else _CHART_TTL_DAILY
        )
        await self._cache_set(cache_key, response, ttl)
        return response

    async def get_market_status(self) -> dict[str, Any]:
        cache_key = _MARKET_STATUS_KEY
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        status = await self._alpaca_clock()
        await self._cache_set(cache_key, status, _MARKET_STATUS_TTL)
        return status

    # ── Cached fetchers ────────────────────────────────────

    async def _get_quote_cached(self, symbol: str) -> dict[str, Any]:
        cache_key = f"market:quote:{symbol}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        raw = await self._fmp.quote(symbol)
        projected = project_quote(raw)
        ttl = await self._quote_ttl()
        await self._cache_set(cache_key, projected, ttl)
        return projected

    async def _get_fundamentals_cached(self, symbol: str) -> dict[str, Any]:
        cache_key = f"market:fundamentals:{symbol}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        profile_raw, ratios_raw = await asyncio.gather(
            self._fmp.profile(symbol),
            self._fmp.ratios_ttm(symbol),
        )
        fundamentals = {
            "profile": project_profile(profile_raw),
            "ratios": project_ratios(ratios_raw),
        }
        await self._cache_set(cache_key, fundamentals, _FUNDAMENTALS_TTL)
        return fundamentals

    async def _get_analyst_cached(self, symbol: str) -> dict[str, Any]:
        cache_key = f"market:analyst:{symbol}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        targets, ratings = await asyncio.gather(
            self._fmp.price_target_consensus(symbol),
            self._fmp.upgrades_downgrades_consensus(symbol),
        )
        analyst = project_analyst(targets, ratings)
        await self._cache_set(cache_key, analyst, _FUNDAMENTALS_TTL)
        return analyst

    async def _is_market_open(self) -> bool:
        status = await self.get_market_status()
        return bool(status.get("is_open", False))

    async def _quote_ttl(self) -> int:
        """Pick quote TTL based on market hours; fall back to the short TTL
        if Alpaca's clock is unreachable so a transient clock outage doesn't
        drop fresh FMP data on the floor.
        """
        try:
            is_open = await self._is_market_open()
        except (MarketDataUnavailableError, MarketDataUpstreamError) as exc:
            logger.warning("market_data_clock_unavailable", error=str(exc))
            return _QUOTE_TTL
        return _QUOTE_TTL if is_open else _QUOTE_TTL_CLOSED

    # ── Cache helpers ──────────────────────────────────────

    async def _cache_get(self, key: str) -> Any:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning("market_data_cache_get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "market_data_cache_decode_failed", key=key, error=str(exc)
            )
            return None

    async def _cache_set(self, key: str, data: Any, ttl: int) -> None:
        try:
            await self._redis.set(key, json.dumps(data), ex=ttl)
        except Exception as exc:
            logger.warning("market_data_cache_set_failed", key=key, error=str(exc))

    # ── Alpaca Market Data ─────────────────────────────────

    async def _alpaca_headers(self) -> dict[str, str]:
        try:
            token = await self._alpaca_broker.access_token()
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            # Surface as a market-data-shaped 503 instead of a brokerage 5xx
            # so the caller's error handling can stay in one domain.
            logger.error("alpaca_data_token_failed", error=str(exc))
            raise MarketDataUnavailableError() from exc
        return {"Authorization": f"Bearer {token}"}

    async def _alpaca_bars(
        self, symbol: str, timeframe: str, days_back: int
    ) -> list[dict[str, Any]]:
        start = (
            datetime.now(timezone.utc) - timedelta(days=days_back)
        ).isoformat()
        path = f"/v2/stocks/{symbol}/bars"
        params = {
            "timeframe": timeframe,
            "start": start,
            "limit": 10000,
            "adjustment": "split",
            "feed": "iex",
            "sort": "asc",
        }
        body = await self._alpaca_get(
            f"{self._alpaca_data_url}{path}", params=params, log_path=path
        )
        raw_bars = body.get("bars", []) or []
        return [
            {
                "timestamp": bar["t"],
                "open": str(bar["o"]),
                "high": str(bar["h"]),
                "low": str(bar["l"]),
                "close": str(bar["c"]),
                "volume": bar["v"],
                "vwap": str(bar.get("vw", "0")),
                "trade_count": bar.get("n", 0),
            }
            for bar in raw_bars
        ]

    async def _alpaca_clock(self) -> dict[str, Any]:
        path = "/v1/clock"
        body = await self._alpaca_get(
            f"{self._alpaca_broker_url}{path}", log_path=path
        )
        return {
            "is_open": bool(body.get("is_open", False)),
            "next_open": str(body.get("next_open", "")),
            "next_close": str(body.get("next_close", "")),
            "timestamp": str(body.get("timestamp", "")),
        }

    async def _alpaca_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        log_path: str,
    ) -> dict[str, Any]:
        headers = await self._alpaca_headers()
        try:
            response = await self._alpaca_client.get(
                url, params=params, headers=headers
            )
        except httpx.HTTPError as exc:
            logger.error(
                "alpaca_data_connection_failed", path=log_path, error=str(exc)
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("alpaca_data_path", log_path)
                sentry_sdk.capture_exception(exc)
            raise MarketDataUnavailableError() from exc

        if response.status_code != 200:
            body_preview = redact_bearer(response.text[:BODY_LOG_LIMIT])
            logger.warning(
                "alpaca_data_api_error",
                path=log_path,
                status_code=response.status_code,
                body=body_preview,
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("alpaca_data_path", log_path)
                scope.set_tag("alpaca_data_status", str(response.status_code))
                sentry_sdk.capture_message("alpaca_data_api_error", level="warning")
            raise MarketDataUpstreamError(status_code=response.status_code)

        logger.info(
            "alpaca_data_api_ok",
            path=log_path,
            status_code=response.status_code,
        )
        return response.json()


def _normalize_symbol(symbol: str) -> str:
    """Uppercase + strip + validate. Raises `MarketDataInvalidInputError`.

    Centralizes the contract so cache keys and upstream URLs cannot diverge
    (e.g. "aapl" and "AAPL" caching twice) and so user-supplied path
    segments cannot smuggle separators ("/", ",") into Alpaca/FMP URLs.
    """
    if not symbol or not isinstance(symbol, str):
        raise MarketDataInvalidInputError("Symbol cannot be empty")
    cleaned = symbol.strip().upper()
    if not _SYMBOL_RE.match(cleaned):
        raise MarketDataInvalidInputError(
            f"Invalid symbol: {symbol}", symbol=symbol
        )
    return cleaned


def get_market_data_service(request: Request) -> MarketDataService:
    """FastAPI dependency yielding the singleton service or a 503.

    `app.state.market_data` is None in dev when `FMP_API_KEY` is unset
    (so unrelated workflows still boot). Routes that depend on this
    helper get a clean `MarketDataUnavailableError` → 503 instead of an
    `AttributeError` on a None reference.
    """
    service: MarketDataService | None = request.app.state.market_data
    if service is None:
        raise MarketDataUnavailableError()
    return service
