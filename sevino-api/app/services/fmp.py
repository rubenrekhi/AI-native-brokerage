from datetime import date, datetime, timezone
from typing import Any, ClassVar

import httpx
import sentry_sdk
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services._http import BODY_LOG_LIMIT

logger = structlog.get_logger(__name__)


def str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def none_if_blank(value: Any) -> Any:
    """Return None for None or empty/whitespace string; otherwise pass through.

    Unlike `value or None`, this preserves falsy values like 0 and False.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def int_or_zero(value: Any) -> int:
    """Coerce missing or null integer fields to 0 while preserving real 0."""
    if value is None:
        return 0
    return int(value)


def _redact(text: str, secret: str) -> str:
    if not text or not secret:
        return text
    return text.replace(secret, "***")


def _comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class _FmpNewsItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    headline: str = Field(alias="title")
    source: str | None = Field(default=None, alias="site")
    url: str
    published_at: datetime = Field(alias="publishedDate")
    summary: str | None = Field(default=None, alias="text")
    image_url: str | None = Field(default=None, alias="image")

    @field_validator("source", "summary", "image_url", mode="before")
    @classmethod
    def _none_if_blank(cls, value: Any) -> Any:
        return none_if_blank(value)


class StockNewsItem(_FmpNewsItem):
    symbol: str


class GeneralNewsItem(_FmpNewsItem):
    pass


def _fmp_news_from_date(since: datetime) -> str:
    return _comparable_datetime(since).date().isoformat()


def _fmp_news_request_limit(since: datetime, limit: int) -> int:
    cutoff = _comparable_datetime(since)
    if (
        cutoff.hour == 0
        and cutoff.minute == 0
        and cutoff.second == 0
        and cutoff.microsecond == 0
    ):
        return limit
    return max(limit, min(max(limit * 3, 100), 500))


def _validate_news_items[T: _FmpNewsItem](
    rows: list[dict[str, Any]] | None, item_type: type[T]
) -> list[T]:
    news: list[T] = []
    for index, row in enumerate(rows or []):
        try:
            news.append(item_type.model_validate(row))
        except ValidationError as exc:
            logger.warning(
                "fmp_news_item_invalid",
                item_type=item_type.__name__,
                index=index,
                error_count=exc.error_count(),
            )
    return news


class FmpClient:
    """HTTP client for Financial Modeling Prep API.

    The HTTP client is reused for the lifetime of the process; construct
    one in `lifecycle.lifespan` and call `await close()` on shutdown.

    Most endpoint methods return raw FMP JSON shapes. Use the `project_*`
    helpers to map them to our schema shape. News methods return validated
    news item models because their callers consume those typed rows directly.
    """

    DEFAULT_BASE_URL: ClassVar[str] = "https://financialmodelingprep.com/stable"
    BATCH_QUOTE_MAX_SYMBOLS: ClassVar[int] = 100

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("FmpClient requires a non-empty api_key")
        self._api_key = api_key
        self._base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        base_url = self._base_url.rstrip("/")
        if (
            base_url.endswith("/stable")
            and (path.startswith("/api/v3/") or path.startswith("/api/v4/"))
        ):
            # FMP's legacy news endpoints live under /api/v3 and /api/v4,
            # while this client defaults to the newer /stable base path.
            base_url = base_url.removesuffix("/stable")
        url = f"{base_url}{path}"
        query: dict[str, Any] = {"apikey": self._api_key}
        if params:
            query.update(params)
        try:
            resp = await self._client.get(url, params=query)
        except httpx.HTTPError as exc:
            # FMP attaches the api key as a query param; httpx error messages
            # frequently echo the URL, so redact the key before logging.
            safe_error = _redact(str(exc), self._api_key)
            logger.error("fmp_connection_failed", error=safe_error, path=path)
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("fmp_path", path)
                scope.set_context(
                    "fmp_request",
                    {"path": path, "error": safe_error},
                )
                sentry_sdk.capture_exception(exc)
            raise MarketDataUnavailableError() from exc

        if resp.status_code != 200:
            # 402 from FMP means "this symbol isn't in your subscription
            # tier" — a permanent per-ticker coverage gap, not a transient
            # outage. Short-circuit *before* the warning log and Sentry
            # capture below: this is an expected no-op for unsupported
            # tickers and shouldn't page on-call. Surface as
            # `MarketDataError` (the "no data for ticker" branch) so the
            # agent tells the user the ticker isn't supported instead of
            # "temporarily unavailable, please retry."
            if resp.status_code == 402:
                symbol = params.get("symbol", "") if params else ""
                logger.info(
                    "fmp_symbol_not_in_tier",
                    path=path,
                    symbol=symbol or None,
                )
                raise MarketDataError(
                    f"FMP 402: symbol {symbol or 'unknown'} not in subscription tier",
                    symbol=str(symbol),
                )

            safe_body = _redact(resp.text[:BODY_LOG_LIMIT], self._api_key)
            logger.warning(
                "fmp_api_error",
                status_code=resp.status_code,
                path=path,
                body=safe_body,
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("fmp_path", path)
                scope.set_tag("fmp_status", str(resp.status_code))
                scope.set_context(
                    "fmp_request",
                    {
                        "path": path,
                        "status_code": resp.status_code,
                        "body": safe_body,
                    },
                )
                sentry_sdk.capture_message("fmp_api_error", level="warning")
            raise MarketDataUpstreamError(status_code=resp.status_code)
        return resp.json()

    async def quote(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/quote", {"symbol": symbol})
        if not data:
            raise MarketDataError(f"No quote data for {symbol}", symbol=symbol)
        return data[0]

    async def batch_quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch quotes for multiple symbols. Returns raw FMP dicts.

        Requests larger than `BATCH_QUOTE_MAX_SYMBOLS` are split into
        chunks. Symbols missing from the FMP response are silently
        dropped from the result.
        """
        if not symbols:
            return []
        results: list[dict[str, Any]] = []
        for i in range(0, len(symbols), self.BATCH_QUOTE_MAX_SYMBOLS):
            chunk = symbols[i : i + self.BATCH_QUOTE_MAX_SYMBOLS]
            data = await self._request("/batch-quote", {"symbols": ",".join(chunk)})
            if data:
                results.extend(data)
        return results

    async def profile(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/profile", {"symbol": symbol})
        if not data:
            raise MarketDataError(f"No profile data for {symbol}", symbol=symbol)
        return data[0]

    async def ratios_ttm(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/ratios-ttm", {"symbol": symbol})
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def price_target_consensus(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/price-target-consensus", {"symbol": symbol})
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def grades_consensus(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/grades-consensus", {"symbol": symbol})
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def earnings_calendar(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        """Earnings events between two dates (inclusive). Raw FMP rows.

        An empty window legitimately returns ``[]`` (no upcoming earnings),
        so — unlike the per-symbol endpoints — an empty payload is not an
        error.
        """
        data = await self._request(
            "/earnings-calendar",
            {"from": from_date.isoformat(), "to": to_date.isoformat()},
        )
        return data or []

    async def dividend_calendar(
        self, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        """Dividend events between two dates (inclusive). Raw FMP rows.

        Like :meth:`earnings_calendar`, an empty window returns ``[]``.
        """
        data = await self._request(
            "/dividends-calendar",
            {"from": from_date.isoformat(), "to": to_date.isoformat()},
        )
        return data or []

    async def get_stock_news(
        self, symbols: list[str], since: datetime, limit: int = 50
    ) -> list[StockNewsItem]:
        """Stock news for the requested symbols, newest rows at or after ``since``.

        FMP's ``from`` parameter is date-granular, so sub-day ``since`` filters
        are applied client-side after requesting headroom for same-day rows.
        """
        if limit <= 0:
            return []
        tickers = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not tickers:
            return []

        data = await self._request(
            "/api/v3/stock_news",
            {
                "tickers": ",".join(tickers),
                "from": _fmp_news_from_date(since),
                "limit": _fmp_news_request_limit(since, limit),
            },
        )
        news = _validate_news_items(data, StockNewsItem)
        cutoff = _comparable_datetime(since)
        return [
            item
            for item in news
            if _comparable_datetime(item.published_at) >= cutoff
        ][:limit]

    async def get_general_news(
        self, since: datetime, limit: int = 20
    ) -> list[GeneralNewsItem]:
        """General market news, newest rows at or after ``since``.

        FMP's ``from`` parameter is date-granular, so sub-day ``since`` filters
        are applied client-side after requesting headroom for same-day rows.
        """
        if limit <= 0:
            return []

        data = await self._request(
            "/api/v4/general_news",
            {
                "from": _fmp_news_from_date(since),
                "limit": _fmp_news_request_limit(since, limit),
            },
        )
        news = _validate_news_items(data, GeneralNewsItem)
        cutoff = _comparable_datetime(since)
        return [
            item
            for item in news
            if _comparable_datetime(item.published_at) >= cutoff
        ][:limit]


def project_quote(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": raw.get("symbol", ""),
        "name": raw.get("name", ""),
        "price": str(raw.get("price", 0)),
        "change": str(raw.get("change", 0)),
        "change_percent": str(raw.get("changePercentage", 0)),
        "open": str(raw.get("open", 0)),
        "day_high": str(raw.get("dayHigh", 0)),
        "day_low": str(raw.get("dayLow", 0)),
        "previous_close": str(raw.get("previousClose", 0)),
        "volume": int_or_zero(raw.get("volume")),
        "avg_volume": int_or_zero(raw.get("avgVolume")),
        "market_cap": int_or_zero(raw.get("marketCap")),
        "pe_ratio": str_or_none(raw.get("pe")),
        "eps": str_or_none(raw.get("eps")),
        "year_high": str(raw.get("yearHigh", 0)),
        "year_low": str(raw.get("yearLow", 0)),
        "price_avg_50": str(raw.get("priceAvg50", 0)),
        "price_avg_200": str(raw.get("priceAvg200", 0)),
        "shares_outstanding": int_or_zero(raw.get("sharesOutstanding")),
        "earnings_announcement": raw.get("earningsAnnouncement"),
        "timestamp": int_or_zero(raw.get("timestamp")),
    }


def project_profile(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("companyName", ""),
        "sector": none_if_blank(raw.get("sector")),
        "industry": none_if_blank(raw.get("industry")),
        "description": none_if_blank(raw.get("description")),
        "ceo": none_if_blank(raw.get("ceo")),
        "website": none_if_blank(raw.get("website")),
        "employees": none_if_blank(raw.get("fullTimeEmployees")),
        "beta": str_or_none(raw.get("beta")),
        "ipo_date": none_if_blank(raw.get("ipoDate")),
        "exchange": raw.get("exchangeShortName", ""),
        "logo_url": none_if_blank(raw.get("image")),
    }


def project_ratios(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "dividend_yield": str_or_none(raw.get("dividendYieldTTM")),
        "payout_ratio": str_or_none(raw.get("payoutRatioTTM")),
        "roe": str_or_none(raw.get("returnOnEquityTTM")),
        "roa": str_or_none(raw.get("returnOnAssetsTTM")),
        "profit_margin": str_or_none(raw.get("netProfitMarginTTM")),
        "operating_margin": str_or_none(raw.get("operatingProfitMarginTTM")),
        "gross_margin": str_or_none(raw.get("grossProfitMarginTTM")),
        "debt_to_equity": str_or_none(raw.get("debtEquityRatioTTM")),
        "current_ratio": str_or_none(raw.get("currentRatioTTM")),
        "price_to_book": str_or_none(raw.get("priceToBookRatioTTM")),
        "price_to_sales": str_or_none(raw.get("priceToSalesRatioTTM")),
        "ev_to_ebitda": str_or_none(raw.get("enterpriseValueMultipleTTM")),
        "free_cash_flow_yield": str_or_none(raw.get("freeCashFlowYieldTTM")),
        "peg_ratio": str_or_none(raw.get("priceEarningsToGrowthRatioTTM")),
    }


def project_analyst(
    targets: dict[str, Any], ratings: dict[str, Any]
) -> dict[str, Any]:
    return {
        "target_high": str_or_none(targets.get("targetHigh")),
        "target_low": str_or_none(targets.get("targetLow")),
        "target_consensus": str_or_none(targets.get("targetConsensus")),
        "target_median": str_or_none(targets.get("targetMedian")),
        "strong_buy": ratings.get("strongBuy"),
        "buy": ratings.get("buy"),
        "hold": ratings.get("hold"),
        "sell": ratings.get("sell"),
        "strong_sell": ratings.get("strongSell"),
    }
