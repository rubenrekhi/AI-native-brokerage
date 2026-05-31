import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
import sentry_sdk
import structlog
from fastapi import Request
from redis.asyncio import Redis

from app.config import settings
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
    _parse_iso_date,
    compute_earnings_reactions,
    project_analyst,
    project_earnings,
    project_financials,
    project_profile,
    project_quote,
    project_ratios,
    project_valuation,
)

logger = structlog.get_logger(__name__)


__all__ = [
    "MarketDataError",
    "MarketDataInvalidInputError",
    "MarketDataUnavailableError",
    "MarketDataUpstreamError",
    "MarketDataService",
    "build_market_data_service",
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
_ANNUAL_TREND_YEARS = 4
_VALUATION_HISTORY_YEARS = 5
_EARNINGS_ACTUALS = 4
# Fetch more reported quarters than we surface so the typical-move average has a
# stable sample, and pull plenty of estimate rows because FMP returns them
# newest-first across several years (the upcoming period is selected by date).
_EARNINGS_HISTORY_ROWS = 8
_EARNINGS_ESTIMATE_ROWS = 16
_EARNINGS_REACTION_LOOKBACK_DAYS = 730

# Sector/industry P/E benchmarks aren't symbol-specific and move slowly, so
# they're cached per exchange with a daily TTL and shared across every symbol
# on that exchange (rather than refetched into each symbol's fundamentals blob).
_SECTOR_PE_TTL = 86400
# Snapshots are empty on weekends/holidays; walk back this many calendar days
# to the last session before giving up (covers a long-weekend closure).
_TRADING_DAY_LOOKBACK = 4

# `FmpClient._request` raises only these on a per-call failure; catch them so a
# missing benchmark or ratios fetch degrades its own fields instead of the
# whole stock-info lookup.
_FMP_FETCH_ERRORS = (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
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
            "financials": fundamentals["financials"],
            "valuation": fundamentals["valuation"],
            "earnings": fundamentals["earnings"],
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

    async def get_stock_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """Fetch projected Alpaca stock bars for internal batch workflows."""
        symbol = _normalize_symbol(symbol)
        return await self._alpaca_bars(
            symbol,
            timeframe,
            start=start,
            end=end,
            limit=limit,
        )

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
            # Entries written before financials/valuation existed lack the key;
            # backfill an empty block so the response shape stays stable until
            # the 12h TTL rolls the entry over.
            cached.setdefault("financials", _empty_financials())
            cached.setdefault("valuation", _empty_valuation())
            cached.setdefault("earnings", _empty_earnings())
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        (
            profile_raw,
            ratios_raw,
            financials,
            annual_ratios,
            earnings,
        ) = await asyncio.gather(
            self._fmp.profile(symbol),
            self._fmp.ratios_ttm(symbol),
            self._fetch_financials(symbol),
            self._fetch_annual_ratios(symbol),
            self._fetch_earnings(symbol),
        )
        valuation = await self._fetch_valuation(
            ratios_raw,
            annual_ratios,
            sector=profile_raw.get("sector"),
            industry=profile_raw.get("industry"),
            exchange=profile_raw.get("exchange"),
        )
        fundamentals = {
            "profile": project_profile(profile_raw),
            "ratios": project_ratios(ratios_raw),
            "financials": financials,
            "valuation": valuation,
            "earnings": earnings,
        }
        await self._cache_set(cache_key, fundamentals, _FUNDAMENTALS_TTL)
        return fundamentals

    async def _fetch_financials(self, symbol: str) -> dict[str, Any]:
        """Fetch the three TTM statements plus annual history and project them.

        Best-effort: each statement is fetched independently and a failure
        degrades only the affected fields to null. This never raises into
        ``get_stock_info`` — quote/profile/ratios/analyst must still return
        when a statement endpoint is slow or a company lacks filings.
        """
        results = await asyncio.gather(
            self._fmp.income_statement_ttm(symbol),
            self._fmp.balance_sheet_ttm(symbol),
            self._fmp.cash_flow_ttm(symbol),
            self._fmp.income_statement_annual(symbol, limit=_ANNUAL_TREND_YEARS),
            return_exceptions=True,
        )
        labels = ("income_ttm", "balance_ttm", "cash_flow_ttm", "annual_income")
        cleaned: list[Any] = []
        for label, result in zip(labels, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "market_data_financials_unavailable",
                    symbol=symbol,
                    statement=label,
                    error=str(result),
                    exc_type=type(result).__name__,
                )
                cleaned.append([] if label == "annual_income" else {})
            else:
                cleaned.append(result)
        income_ttm, balance_ttm, cash_flow_ttm, annual_income = cleaned
        return project_financials(
            income_ttm, balance_ttm, cash_flow_ttm, annual_income
        )

    async def _fetch_annual_ratios(self, symbol: str) -> list[dict[str, Any]]:
        """Annual valuation ratios for the self-history range. Best-effort."""
        try:
            return await self._fmp.ratios_annual(
                symbol, limit=_VALUATION_HISTORY_YEARS
            )
        except _FMP_FETCH_ERRORS as exc:
            logger.warning(
                "market_data_annual_ratios_unavailable",
                symbol=symbol,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return []

    async def _fetch_earnings(self, symbol: str) -> dict[str, Any]:
        """Fetch estimates, quarterly actuals, and daily bars, then project them.

        Three independent failure domains: FMP earnings, FMP estimates, and the
        Alpaca daily bars used for the post-earnings reaction. Each is captured
        separately so a bar-fetch outage degrades only the reaction fields while
        estimates and actuals still populate (and vice versa). Never raises into
        ``get_stock_info``.
        """
        earnings_result, estimates_result, bars_result = await asyncio.gather(
            self._fmp.earnings(symbol, limit=_EARNINGS_HISTORY_ROWS),
            self._fmp.analyst_estimates(symbol, limit=_EARNINGS_ESTIMATE_ROWS),
            self._alpaca_bars(symbol, "1Day", _EARNINGS_REACTION_LOOKBACK_DAYS),
            return_exceptions=True,
        )
        earnings_rows = _earnings_rows_or_empty(earnings_result, symbol, "earnings")
        estimate_rows = _earnings_rows_or_empty(
            estimates_result, symbol, "analyst_estimates"
        )
        bars = _earnings_rows_or_empty(bars_result, symbol, "reaction_bars")

        report_dates = [
            parsed
            for row in earnings_rows
            if (parsed := _parse_iso_date(row.get("date"))) is not None
        ]
        reactions = compute_earnings_reactions(report_dates, bars)
        return project_earnings(
            earnings_rows,
            estimate_rows,
            reactions,
            as_of=datetime.now(timezone.utc).date(),
            actuals_limit=_EARNINGS_ACTUALS,
        )

    async def _fetch_valuation(
        self,
        ratios_ttm: dict[str, Any],
        annual_ratios: list[dict[str, Any]],
        *,
        sector: str | None,
        industry: str | None,
        exchange: str | None,
    ) -> dict[str, Any]:
        """Project the valuation-context block. Best-effort.

        The sector/industry benchmarks are exchange-scoped and not
        symbol-specific, so they're fetched through a per-exchange daily cache.
        A benchmark failure degrades only the vs-sector/vs-industry fields; the
        company's own P/E and historical range still populate.
        """
        sector_rows: list[dict[str, Any]] = []
        industry_rows: list[dict[str, Any]] = []
        as_of_date: str | None = None
        if exchange:
            sector_rows, industry_rows, as_of_date = (
                await self._get_sector_pe_cached(exchange)
            )
        return project_valuation(
            ratios_ttm,
            sector_rows,
            industry_rows,
            annual_ratios,
            sector=sector,
            industry=industry,
            exchange=exchange,
            as_of_date=as_of_date,
        )

    async def _get_sector_pe_cached(
        self, exchange: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        # One key for both snapshots so they share a single atomic expiry
        # rather than drifting out of sync under independent eviction.
        cache_key = f"market:valuation_pe:{exchange}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return (
                cached.get("sector_rows", []),
                cached.get("industry_rows", []),
                cached.get("as_of_date"),
            )

        logger.info("market_data_cache_miss", key=cache_key)
        # Resolve the two snapshots independently: a failure in one must not
        # discard a successful result from the other, so exceptions are
        # captured per-coroutine instead of unwinding the whole gather.
        sector_result, industry_result = await asyncio.gather(
            self._snapshot_with_fallback(self._fmp.sector_pe, exchange),
            self._snapshot_with_fallback(self._fmp.industry_pe, exchange),
            return_exceptions=True,
        )
        sector_rows, sector_date, sector_ok = _unwrap_snapshot(
            sector_result, exchange, "sector"
        )
        industry_rows, industry_date, industry_ok = _unwrap_snapshot(
            industry_result, exchange, "industry"
        )
        as_of_date = sector_date or industry_date

        # Cache only when neither side hit a transient error: a clean empty
        # result (an exchange FMP doesn't cover) is worth caching so we don't
        # re-walk the date window every request, but a 5xx should be retried.
        if sector_ok and industry_ok:
            await self._cache_set(
                cache_key,
                {
                    "sector_rows": sector_rows,
                    "industry_rows": industry_rows,
                    "as_of_date": as_of_date,
                },
                _SECTOR_PE_TTL,
            )
        return sector_rows, industry_rows, as_of_date

    async def _snapshot_with_fallback(
        self,
        fetcher: Callable[[str, str], Awaitable[list[dict[str, Any]]]],
        exchange: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Walk back from today to the last session that has snapshot rows."""
        today = datetime.now(timezone.utc).date()
        for delta in range(_TRADING_DAY_LOOKBACK + 1):
            on_date = (today - timedelta(days=delta)).isoformat()
            rows = await fetcher(exchange, on_date)
            if rows:
                return rows, on_date
        return [], None

    async def _get_analyst_cached(self, symbol: str) -> dict[str, Any]:
        cache_key = f"market:analyst:{symbol}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.info("market_data_cache_hit", key=cache_key)
            return cached

        logger.info("market_data_cache_miss", key=cache_key)
        targets, ratings = await asyncio.gather(
            self._fmp.price_target_consensus(symbol),
            self._fmp.grades_consensus(symbol),
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
        self,
        symbol: str,
        timeframe: str,
        days_back: int | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        if start is None:
            if days_back is None:
                raise ValueError("days_back or start is required")
            start = datetime.now(timezone.utc) - timedelta(days=days_back)
        path = f"/v2/stocks/{symbol}/bars"
        params = {
            "timeframe": timeframe,
            "start": start.isoformat(),
            "limit": limit,
            "adjustment": "split",
            "feed": "iex",
            "sort": "asc",
        }
        if end is not None:
            params["end"] = end.isoformat()
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


def _empty_financials() -> dict[str, Any]:
    return project_financials({}, {}, {}, [])


def _empty_valuation() -> dict[str, Any]:
    return project_valuation(
        {}, [], [], [], sector=None, industry=None, exchange=None, as_of_date=None
    )


def _empty_earnings() -> dict[str, Any]:
    return project_earnings([], [], {}, as_of=date.min)


def _earnings_rows_or_empty(
    result: Any, symbol: str, source: str
) -> list[dict[str, Any]]:
    """Unwrap a `gather(return_exceptions=True)` earnings result.

    A failed fetch degrades only its own fields; the other two earnings sources
    still populate, so a raised exception is logged and dropped to ``[]``.
    """
    if isinstance(result, BaseException):
        logger.warning(
            "market_data_earnings_unavailable",
            symbol=symbol,
            source=source,
            error=str(result),
            exc_type=type(result).__name__,
        )
        return []
    return result


def _unwrap_snapshot(
    result: Any, exchange: str, label: str
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Split a `gather(return_exceptions=True)` snapshot result.

    Returns ``(rows, as_of_date, ok)`` where ``ok`` is False when the fetch
    raised, so the caller can keep a successful sibling but skip caching a
    transient failure.
    """
    if isinstance(result, BaseException):
        logger.warning(
            "market_data_sector_pe_unavailable",
            exchange=exchange,
            snapshot=label,
            error=str(result),
            exc_type=type(result).__name__,
        )
        return [], None, False
    rows, on_date = result
    return rows, on_date, True


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


def build_market_data_service(
    *,
    fmp: FmpClient,
    alpaca_broker: AccessTokenProvider,
    redis: Redis,
) -> MarketDataService:
    return MarketDataService(
        fmp=fmp,
        alpaca_broker=alpaca_broker,
        redis=redis,
        alpaca_data_url=settings.alpaca_data_base_url,
        alpaca_broker_url=settings.alpaca_base_url,
    )


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
