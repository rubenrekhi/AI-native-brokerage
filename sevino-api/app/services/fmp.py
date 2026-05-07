from typing import Any, ClassVar

import httpx
import sentry_sdk
import structlog

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


class FmpClient:
    """HTTP client for Financial Modeling Prep API.

    The HTTP client is reused for the lifetime of the process; construct
    one in `lifecycle.lifespan` and call `await close()` on shutdown.

    Endpoint methods return raw FMP JSON shapes. Use the `project_*`
    helpers to map them to our schema shape.
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
        url = f"{self._base_url}{path}"
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
