from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ChartTimeframe(str, Enum):
    ONE_DAY = "1D"
    ONE_WEEK = "1W"
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    ONE_YEAR = "1Y"
    FIVE_YEARS = "5Y"


class StockQuote(BaseModel):
    symbol: str
    name: str
    price: str
    change: str
    change_percent: str
    open: str
    day_high: str
    day_low: str
    previous_close: str
    volume: int
    avg_volume: int
    market_cap: int
    pe_ratio: str | None = None
    eps: str | None = None
    year_high: str
    year_low: str
    price_avg_50: str
    price_avg_200: str
    shares_outstanding: int
    earnings_announcement: str | None = None
    timestamp: int


class StockProfile(BaseModel):
    name: str
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    ceo: str | None = None
    website: str | None = None
    employees: int | None = None
    beta: str | None = None
    ipo_date: str | None = None
    exchange: str
    logo_url: str | None = None


class StockRatios(BaseModel):
    dividend_yield: str | None = None
    payout_ratio: str | None = None
    roe: str | None = None
    roa: str | None = None
    profit_margin: str | None = None
    operating_margin: str | None = None
    gross_margin: str | None = None
    debt_to_equity: str | None = None
    current_ratio: str | None = None
    price_to_book: str | None = None
    price_to_sales: str | None = None
    ev_to_ebitda: str | None = None
    free_cash_flow_yield: str | None = None
    peg_ratio: str | None = None


class StockAnalyst(BaseModel):
    target_high: str | None = None
    target_low: str | None = None
    target_consensus: str | None = None
    target_median: str | None = None
    strong_buy: int | None = None
    buy: int | None = None
    hold: int | None = None
    sell: int | None = None
    strong_sell: int | None = None


class StockInfoResponse(BaseModel):
    quote: StockQuote
    profile: StockProfile
    ratios: StockRatios
    analyst: StockAnalyst


class BatchQuoteResponse(BaseModel):
    quotes: list[StockQuote]


class PriceBar(BaseModel):
    timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: int
    vwap: str
    trade_count: int


class ChartResponse(BaseModel):
    symbol: str
    timeframe: ChartTimeframe
    bars: list[PriceBar]


class MarketStatusResponse(BaseModel):
    is_open: bool
    next_open: str
    next_close: str
    timestamp: str
