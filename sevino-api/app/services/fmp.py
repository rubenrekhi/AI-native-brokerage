from datetime import date, datetime, timezone
from typing import Any, ClassVar, TypeVar

import httpx
import sentry_sdk
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.schemas.fmp import EarningsCalendarItem, HistoricalEarningsItem
from app.services._http import BODY_LOG_LIMIT

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


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


def _validate_fmp_rows(
    raw: Any,
    model: type[T],
    *,
    log_event: str,
) -> list[T]:
    """Validate FMP row lists, dropping malformed rows without killing the batch."""
    if not raw:
        return []
    if not isinstance(raw, list):
        logger.warning(
            "fmp_unexpected_payload_shape",
            log_event=log_event,
            payload_type=type(raw).__name__,
        )
        return []

    items: list[T] = []
    for row in raw:
        try:
            items.append(model.model_validate(row))
        except ValidationError as exc:
            logger.warning(
                log_event,
                raw_keys=list(row.keys()) if isinstance(row, dict) else None,
                error=str(exc),
            )
    return items


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
    body: str | None = None
    image_url: str | None = Field(default=None, alias="image")

    @field_validator("source", "summary", "body", "image_url", mode="before")
    @classmethod
    def _none_if_blank(cls, value: Any) -> Any:
        return none_if_blank(value)

    @field_validator("published_at", mode="after")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        # FMP returns naive timestamps; anchor to UTC so the iOS strict ISO 8601 decoder accepts them.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


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
    helpers to map them to our schema shape. Legacy v3 earnings methods and
    news methods return validated models because their callers consume those
    typed rows directly.
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

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        base_url: str | None = None,
        symbol_for_errors: str | None = None,
    ) -> Any:
        resolved_base_url = (base_url or self._base_url).rstrip("/")
        url = f"{resolved_base_url}{path}"
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
                symbol = (
                    symbol_for_errors
                    or (params.get("symbol", "") if params else "")
                    or ""
                )
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

    async def income_statement_ttm(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/income-statement-ttm", {"symbol": symbol})
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def balance_sheet_ttm(self, symbol: str) -> dict[str, Any]:
        data = await self._request(
            "/balance-sheet-statement-ttm", {"symbol": symbol}
        )
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def cash_flow_ttm(self, symbol: str) -> dict[str, Any]:
        data = await self._request("/cash-flow-statement-ttm", {"symbol": symbol})
        if not data:
            return {}
        return data[0] if isinstance(data, list) else data

    async def income_statement_annual(
        self, symbol: str, *, limit: int = 4
    ) -> list[dict[str, Any]]:
        """Annual income statements, newest first. Empty payload returns ``[]``."""
        data = await self._request(
            "/income-statement",
            {"symbol": symbol, "period": "annual", "limit": limit},
        )
        return data or []

    async def ratios_annual(
        self, symbol: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Annual valuation ratios, newest first. Empty payload returns ``[]``."""
        data = await self._request(
            "/ratios",
            {"symbol": symbol, "period": "annual", "limit": limit},
        )
        return data or []

    async def sector_pe(
        self, exchange: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Per-sector P/E for an exchange on a date. Empty payload returns ``[]``.

        Non-trading days legitimately return no rows, so callers walk the date
        back to the last session rather than treating empty as an error.
        """
        data = await self._request(
            "/sector-pe-snapshot",
            {"date": on_date, "exchange": exchange},
        )
        return data or []

    async def industry_pe(
        self, exchange: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Per-industry P/E for an exchange on a date. Empty payload returns ``[]``."""
        data = await self._request(
            "/industry-pe-snapshot",
            {"date": on_date, "exchange": exchange},
        )
        return data or []

    async def sector_performance(
        self, exchange: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Per-sector average price change for an exchange on a date. Empty → ``[]``.

        Like the P/E snapshots, non-trading days return no rows, so callers walk
        the date back to the last session rather than treating empty as an error.
        ``averageChange`` is a percent figure (``0.74`` == +0.74%).
        """
        data = await self._request(
            "/sector-performance-snapshot",
            {"date": on_date, "exchange": exchange},
        )
        return data or []

    async def industry_performance(
        self, exchange: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Per-industry average price change for an exchange on a date. Empty → ``[]``."""
        data = await self._request(
            "/industry-performance-snapshot",
            {"date": on_date, "exchange": exchange},
        )
        return data or []

    async def stock_peers(self, symbol: str) -> list[dict[str, Any]]:
        """Comparable companies for a symbol (name, price, market cap). Empty → ``[]``.

        FMP's peer list is noisy — it mixes mega-caps with micro-caps — so
        callers cap it by market cap rather than trusting the full list.
        """
        data = await self._request("/stock-peers", {"symbol": symbol})
        return data or []

    async def earnings(
        self, symbol: str, *, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Per-symbol earnings actuals + estimates, newest first. Empty → ``[]``.

        Future quarters carry null ``epsActual``/``revenueActual``. FMP exposes
        no pre-/post-market timing on this endpoint.
        """
        data = await self._request("/earnings", {"symbol": symbol, "limit": limit})
        return data or []

    async def analyst_estimates(
        self, symbol: str, *, period: str = "quarter", limit: int = 16
    ) -> list[dict[str, Any]]:
        """Analyst revenue/EPS estimates by period, newest first. Empty → ``[]``.

        Rows are returned newest-first and span several years out, so callers
        select the nearest upcoming period rather than slicing by ``limit``.
        """
        data = await self._request(
            "/analyst-estimates",
            {"symbol": symbol, "period": period, "limit": limit},
        )
        return data or []

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

    async def get_earnings_calendar(
        self, from_date: date, to_date: date
    ) -> list[EarningsCalendarItem]:
        """Earnings calendar rows, validated into schema objects.

        This intentionally coexists with `earnings_calendar`, which returns
        raw rows for the radar event ingester.
        """
        data = await self._request(
            "/earnings-calendar",
            {"from": from_date.isoformat(), "to": to_date.isoformat()},
        )
        items = _validate_fmp_rows(
            data,
            EarningsCalendarItem,
            log_event="fmp_earnings_calendar_row_invalid",
        )
        # FMP can over-include rows near request boundaries; preserve the
        # method's inclusive date-window contract for callers.
        return [
            item for item in items if from_date <= item.reported_date <= to_date
        ]

    async def get_historical_earnings(
        self, symbol: str, limit: int = 8
    ) -> list[HistoricalEarningsItem]:
        if limit <= 0:
            return []

        data = await self._request(
            "/earnings",
            {"symbol": symbol},
            symbol_for_errors=symbol,
        )
        items = _validate_fmp_rows(
            data,
            HistoricalEarningsItem,
            log_event="fmp_historical_earnings_row_invalid",
        )
        items.sort(key=lambda item: item.reported_date, reverse=True)
        return items[:limit]

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
            "/news/stock",
            {
                "symbols": ",".join(tickers),
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
            "/news/general-latest",
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


def _as_number(value: Any) -> float | None:
    """Coerce an FMP numeric field to float, or None if missing/non-numeric.

    Rejects bool: ``isinstance(True, int)`` is True in Python, but a bool is
    never a valid financial figure.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _growth(current: Any, prior: Any) -> float | None:
    """Year-over-year growth as a decimal ratio (0.06 == +6%).

    Returns None when either value is missing or the prior value is not
    strictly positive — a non-positive base makes a growth percentage
    meaningless (e.g. swinging out of a loss), so we omit it rather than
    emit a misleading number.
    """
    cur = _as_number(current)
    prev = _as_number(prior)
    if cur is None or prev is None or prev <= 0:
        return None
    return round((cur - prev) / prev, 4)


def _build_annual_trend(
    annual_income: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "fiscal_year": str_or_none(row.get("fiscalYear")),
            "period_end_date": none_if_blank(row.get("date")),
            "revenue": str_or_none(row.get("revenue")),
            "net_income": str_or_none(row.get("netIncome")),
            "eps_diluted": str_or_none(row.get("epsDiluted")),
        }
        for row in annual_income
    ]


def _ttm_period_label(income_ttm: dict[str, Any]) -> str | None:
    end = none_if_blank(income_ttm.get("date"))
    if end is None:
        return None
    return f"TTM through {end}"


def project_financials(
    income_ttm: dict[str, Any],
    balance_ttm: dict[str, Any],
    cash_flow_ttm: dict[str, Any],
    annual_income: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = annual_income[0] if annual_income else {}
    prior = annual_income[1] if len(annual_income) > 1 else {}
    return {
        "revenue": str_or_none(income_ttm.get("revenue")),
        "gross_profit": str_or_none(income_ttm.get("grossProfit")),
        "operating_income": str_or_none(income_ttm.get("operatingIncome")),
        "ebitda": str_or_none(income_ttm.get("ebitda")),
        "net_income": str_or_none(income_ttm.get("netIncome")),
        "eps_diluted": str_or_none(income_ttm.get("epsDiluted")),
        "research_and_development": str_or_none(
            income_ttm.get("researchAndDevelopmentExpenses")
        ),
        "interest_expense": str_or_none(income_ttm.get("interestExpense")),
        "shares_outstanding_diluted": str_or_none(
            income_ttm.get("weightedAverageShsOutDil")
        ),
        "cash_and_short_term_investments": str_or_none(
            balance_ttm.get("cashAndShortTermInvestments")
        ),
        "total_debt": str_or_none(balance_ttm.get("totalDebt")),
        "net_debt": str_or_none(balance_ttm.get("netDebt")),
        "total_assets": str_or_none(balance_ttm.get("totalAssets")),
        "total_liabilities": str_or_none(balance_ttm.get("totalLiabilities")),
        "total_stockholders_equity": str_or_none(
            balance_ttm.get("totalStockholdersEquity")
        ),
        "operating_cash_flow": str_or_none(
            cash_flow_ttm.get("operatingCashFlow")
        ),
        "free_cash_flow": str_or_none(cash_flow_ttm.get("freeCashFlow")),
        "capital_expenditure": str_or_none(
            cash_flow_ttm.get("capitalExpenditure")
        ),
        "revenue_growth_yoy": str_or_none(
            _growth(latest.get("revenue"), prior.get("revenue"))
        ),
        "net_income_growth_yoy": str_or_none(
            _growth(latest.get("netIncome"), prior.get("netIncome"))
        ),
        "eps_growth_yoy": str_or_none(
            _growth(latest.get("epsDiluted"), prior.get("epsDiluted"))
        ),
        "annual_trend": _build_annual_trend(annual_income),
        "fiscal_period": _ttm_period_label(income_ttm),
        "period_end_date": none_if_blank(income_ttm.get("date")),
        "reported_currency": none_if_blank(income_ttm.get("reportedCurrency")),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _pe_premium(company_pe: float | None, benchmark_pe: float | None) -> float | None:
    """Company P/E relative to a benchmark as a decimal (0.20 == 20% richer).

    None unless both P/Es are present and strictly positive. A non-positive
    P/E on either side makes the premium meaningless — a loss-making company
    (negative P/E) would otherwise read as a large bogus discount.
    """
    if company_pe is None or company_pe <= 0:
        return None
    if benchmark_pe is None or benchmark_pe <= 0:
        return None
    return round(company_pe / benchmark_pe - 1, 4)


def _match_pe(rows: list[dict[str, Any]], key: str, value: str | None) -> float | None:
    if not value:
        return None
    for row in rows:
        if row.get(key) == value:
            return _as_number(row.get("pe"))
    return None


def _build_valuation_history(
    annual_ratios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "fiscal_year": str_or_none(row.get("fiscalYear")),
            "pe": str_or_none(row.get("priceToEarningsRatio")),
            "ps": str_or_none(row.get("priceToSalesRatio")),
            "pb": str_or_none(row.get("priceToBookRatio")),
        }
        for row in annual_ratios
    ]


def project_valuation(
    ratios_ttm: dict[str, Any],
    sector_rows: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
    annual_ratios: list[dict[str, Any]],
    *,
    sector: str | None,
    industry: str | None,
    exchange: str | None,
    as_of_date: str | None,
) -> dict[str, Any]:
    sector = none_if_blank(sector)
    industry = none_if_blank(industry)
    exchange = none_if_blank(exchange)

    company_pe = _as_number(ratios_ttm.get("priceToEarningsRatioTTM"))
    sector_pe = _match_pe(sector_rows, "sector", sector)
    industry_pe = _match_pe(industry_rows, "industry", industry)
    matched_benchmark = sector_pe is not None or industry_pe is not None

    # Non-positive P/Es (loss-making years) make a valuation *range* meaningless,
    # so they're excluded from the low/high/median while the raw history below
    # still reports every year.
    pe_series = [
        pe
        for row in annual_ratios
        if (pe := _as_number(row.get("priceToEarningsRatio"))) is not None and pe > 0
    ]
    return {
        "pe": str_or_none(company_pe),
        "sector": sector,
        "industry": industry,
        "exchange": exchange,
        "as_of_date": as_of_date if matched_benchmark else None,
        "sector_pe": str_or_none(sector_pe),
        "industry_pe": str_or_none(industry_pe),
        "pe_vs_sector": str_or_none(_pe_premium(company_pe, sector_pe)),
        "pe_vs_industry": str_or_none(_pe_premium(company_pe, industry_pe)),
        "pe_5y_low": str_or_none(min(pe_series)) if pe_series else None,
        "pe_5y_high": str_or_none(max(pe_series)) if pe_series else None,
        "pe_5y_median": str_or_none(_median(pe_series)),
        "valuation_history": _build_valuation_history(annual_ratios),
    }


def _match_change(
    rows: list[dict[str, Any]], key: str, value: str | None
) -> float | None:
    if not value:
        return None
    for row in rows:
        if row.get(key) == value:
            return _as_number(row.get("averageChange"))
    return None


def _mean_change(rows: list[dict[str, Any]]) -> float | None:
    """Mean ``averageChange`` across a performance snapshot, as a market proxy.

    An equal-weight average of every sector on the exchange — a neutral,
    internally-consistent baseline (same exchange, same methodology) the
    subject's sector is measured against.
    """
    changes = [
        change
        for row in rows
        if (change := _as_number(row.get("averageChange"))) is not None
    ]
    if not changes:
        return None
    return round(sum(changes) / len(changes), 4)


def _select_peers(
    peer_rows: list[dict[str, Any]],
    *,
    subject_symbol: str | None,
    max_peers: int,
) -> list[dict[str, Any]]:
    """Top peers by market cap, dropping the subject and junk (non-positive cap).

    Capping by market cap keeps the comparison to genuinely comparable names
    rather than the micro-caps FMP mixes into its peer list. ``price`` and
    ``change_pct`` are left null here and filled live in
    :func:`compute_peer_comparison`.
    """
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in peer_rows:
        symbol = row.get("symbol")
        if not symbol or symbol == subject_symbol:
            continue
        market_cap = _as_number(row.get("mktCap"))
        if market_cap is None or market_cap <= 0:
            continue
        candidates.append(
            (
                market_cap,
                {
                    "symbol": symbol,
                    "company_name": none_if_blank(row.get("companyName")),
                    "market_cap": int(market_cap),
                    "price": None,
                    "change_pct": None,
                },
            )
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [peer for _cap, peer in candidates[:max_peers]]


def project_sector_context(
    sector_rows: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
    peer_rows: list[dict[str, Any]],
    *,
    subject_symbol: str | None,
    sector: str | None,
    industry: str | None,
    exchange: str | None,
    as_of_date: str | None,
    max_peers: int,
) -> dict[str, Any]:
    """Build the slow-moving half of the sector-context block.

    Computes the subject's sector/industry change vs. the exchange-wide average
    from the daily performance snapshot, and selects the peer set. Live peer
    changes and the subject's rank are layered on later by
    :func:`compute_peer_comparison`. Changes are percent passthrough — the raw
    FMP ``averageChange`` unit — so the field names carry ``_pct``.
    """
    sector = none_if_blank(sector)
    industry = none_if_blank(industry)
    exchange = none_if_blank(exchange)

    sector_change = _match_change(sector_rows, "sector", sector)
    industry_change = _match_change(industry_rows, "industry", industry)
    market_change = _mean_change(sector_rows)
    sector_vs_market = (
        round(sector_change - market_change, 4)
        if sector_change is not None and market_change is not None
        else None
    )
    matched_benchmark = sector_change is not None or industry_change is not None
    peers = _select_peers(
        peer_rows, subject_symbol=subject_symbol, max_peers=max_peers
    )
    return {
        "sector": sector,
        "industry": industry,
        "exchange": exchange,
        "as_of_date": as_of_date if matched_benchmark else None,
        "sector_change_pct": str_or_none(sector_change),
        "industry_change_pct": str_or_none(industry_change),
        "market_change_pct": str_or_none(market_change),
        "sector_vs_market_pct": str_or_none(sector_vs_market),
        "peers": peers,
        "peer_count": len(peers) or None,
        "rank_by_change": None,
        "rank_by_market_cap": None,
    }


def _rank(subject_value: float | None, peer_values: list[float | None]) -> int | None:
    """Competition rank of the subject among itself + peers (``1`` == highest).

    None when the subject value is missing or no peer carries a comparable
    value, so the caller degrades the rank to null rather than emitting a
    meaningless rank of 1-of-1.
    """
    if subject_value is None:
        return None
    comparable = [value for value in peer_values if value is not None]
    if not comparable:
        return None
    return 1 + sum(1 for value in comparable if value > subject_value)


def compute_peer_comparison(
    *,
    subject_change: float | None,
    subject_market_cap: float | None,
    peers: list[dict[str, Any]],
    peer_quotes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """Merge live peer quotes into the stored peer identities and rank the subject.

    Pure so the ranking math is unit-testable without network: the caller
    fetches ``peer_quotes`` (symbol → projected quote) and passes the subject's
    own live figures in. Peers missing a live quote keep their stored market cap
    and a null change, and drop out of whichever ranking they lack a value for.
    """
    enriched: list[dict[str, Any]] = []
    for peer in peers:
        quote = peer_quotes.get(peer["symbol"])
        change_pct = quote.get("change_percent") if quote else None
        price = quote.get("price") if quote else None
        market_cap = (
            quote.get("market_cap") if quote else None
        ) or peer.get("market_cap")
        enriched.append(
            {
                **peer,
                "price": price,
                "change_pct": change_pct,
                "market_cap": market_cap,
            }
        )
    rank_by_change = _rank(
        subject_change, [_as_number(peer["change_pct"]) for peer in enriched]
    )
    rank_by_market_cap = _rank(
        subject_market_cap, [_as_number(peer["market_cap"]) for peer in enriched]
    )
    return enriched, rank_by_change, rank_by_market_cap


def _parse_iso_date(value: Any) -> date | None:
    """Parse an FMP/Alpaca date or ISO timestamp to a ``date`` (date part only)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _surprise_pct(actual: Any, estimated: Any) -> float | None:
    """Beat/miss as a decimal: ``(actual − estimated) / |estimated|``.

    None when either side is missing or the estimate is zero (no meaningful
    base to divide by).
    """
    act = _as_number(actual)
    est = _as_number(estimated)
    if act is None or est is None or est == 0:
        return None
    return round((act - est) / abs(est), 4)


def compute_earnings_reactions(
    report_dates: list[date], daily_bars: list[dict[str, Any]]
) -> dict[date, float]:
    """Signed post-earnings price move per report date, keyed by report date.

    FMP gives no pre-/post-market timing, so the reaction day is unknown: a
    company reporting before the open moves on the report date, one reporting
    after the close moves the next session. The window straddles both —
    last-close-before-report → close of the session *after* the first session
    on or after the report date — so the move is captured either way (at the
    cost of up to one extra day of drift). ``daily_bars`` are Alpaca daily bars
    in ascending order with ``timestamp`` and ``close``. Events missing a bar on
    either side of the window, or with a non-positive prior close, are omitted
    so the caller degrades those fields to null rather than emitting a bogus
    move.
    """
    closes: list[tuple[date, float]] = []
    for bar in daily_bars:
        bar_date = _parse_iso_date(bar.get("timestamp"))
        close = _as_number(bar.get("close"))
        if bar_date is not None and close is not None:
            closes.append((bar_date, close))
    closes.sort(key=lambda item: item[0])

    reactions: dict[date, float] = {}
    for report_date in report_dates:
        prev_close: float | None = None
        end_close: float | None = None
        for index, (bar_date, _close) in enumerate(closes):
            if bar_date < report_date:
                prev_close = _close
            else:
                end_index = index + 1
                if end_index < len(closes):
                    end_close = closes[end_index][1]
                break
        if prev_close is None or end_close is None or prev_close <= 0:
            continue
        reactions[report_date] = round((end_close - prev_close) / prev_close, 4)
    return reactions


def _select_next_estimate(
    estimate_rows: list[dict[str, Any]], as_of: date
) -> dict[str, Any] | None:
    """Nearest upcoming estimate row (min date on or after ``as_of``).

    FMP returns rows newest-first spanning years, so the upcoming period is
    selected by date rather than by position.
    """
    upcoming = [
        (parsed, row)
        for row in estimate_rows
        if (parsed := _parse_iso_date(row.get("date"))) is not None
        and parsed >= as_of
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda item: item[0])[1]


def project_earnings(
    earnings_rows: list[dict[str, Any]],
    estimate_rows: list[dict[str, Any]],
    reactions: dict[date, float],
    *,
    as_of: date,
    actuals_limit: int = 4,
) -> dict[str, Any]:
    next_estimate = _select_next_estimate(estimate_rows, as_of) or {}

    reported = [row for row in earnings_rows if row.get("epsActual") is not None]
    quarterly: list[dict[str, Any]] = []
    for row in reported[:actuals_limit]:
        report_date = _parse_iso_date(row.get("date"))
        move = reactions.get(report_date) if report_date is not None else None
        quarterly.append(
            {
                "report_date": none_if_blank(row.get("date")),
                "eps_actual": str_or_none(row.get("epsActual")),
                "eps_estimated": str_or_none(row.get("epsEstimated")),
                "eps_surprise_pct": str_or_none(
                    _surprise_pct(row.get("epsActual"), row.get("epsEstimated"))
                ),
                "revenue_actual": str_or_none(row.get("revenueActual")),
                "revenue_estimated": str_or_none(row.get("revenueEstimated")),
                "revenue_surprise_pct": str_or_none(
                    _surprise_pct(
                        row.get("revenueActual"), row.get("revenueEstimated")
                    )
                ),
                "price_move_pct": str_or_none(move),
            }
        )

    moves = list(reactions.values())
    avg_move = (
        round(sum(abs(m) for m in moves) / len(moves), 4) if moves else None
    )
    return {
        "next_period_end": none_if_blank(next_estimate.get("date")),
        "revenue_estimate_avg": str_or_none(next_estimate.get("revenueAvg")),
        "revenue_estimate_low": str_or_none(next_estimate.get("revenueLow")),
        "revenue_estimate_high": str_or_none(next_estimate.get("revenueHigh")),
        "eps_estimate_avg": str_or_none(next_estimate.get("epsAvg")),
        "eps_estimate_low": str_or_none(next_estimate.get("epsLow")),
        "eps_estimate_high": str_or_none(next_estimate.get("epsHigh")),
        "num_analysts": next_estimate.get("numAnalystsEps"),
        "quarterly": quarterly,
        "avg_post_earnings_move_pct": str_or_none(avg_move),
        "events_measured": len(moves) if moves else None,
    }
