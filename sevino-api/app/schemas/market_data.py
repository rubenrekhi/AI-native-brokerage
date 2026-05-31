from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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


class FinancialTrendPoint(BaseModel):
    fiscal_year: str | None = None
    period_end_date: str | None = None
    revenue: str | None = None
    net_income: str | None = None
    eps_diluted: str | None = None


class StockFinancials(BaseModel):
    """Absolute company financials from FMP.

    The snapshot figures (income statement, cash flow) are trailing-twelve-month
    (TTM); balance-sheet figures are the latest reported point-in-time (FMP's
    balance-sheet TTM endpoint returns the latest snapshot, not a summed
    window, since a balance sheet is a stock not a flow). The
    ``annual_trend`` and ``*_growth_yoy`` fields are derived from the most recent
    annual filings (latest fiscal year vs. prior), so growth is reported on an
    annual basis even though the headline figures are TTM. Every field is null
    when FMP omits it or returns too few periods to compute it, so the block
    degrades cleanly rather than failing the lookup.
    """

    revenue: str | None = None
    gross_profit: str | None = None
    operating_income: str | None = None
    ebitda: str | None = None
    net_income: str | None = None
    eps_diluted: str | None = None
    research_and_development: str | None = None
    interest_expense: str | None = None
    shares_outstanding_diluted: str | None = None

    cash_and_short_term_investments: str | None = None
    total_debt: str | None = None
    net_debt: str | None = None
    total_assets: str | None = None
    total_liabilities: str | None = None
    total_stockholders_equity: str | None = None

    operating_cash_flow: str | None = None
    free_cash_flow: str | None = None
    capital_expenditure: str | None = None

    revenue_growth_yoy: str | None = None
    net_income_growth_yoy: str | None = None
    eps_growth_yoy: str | None = None

    annual_trend: list[FinancialTrendPoint] = Field(default_factory=list)

    fiscal_period: str | None = None
    period_end_date: str | None = None
    reported_currency: str | None = None


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


class ValuationHistoryPoint(BaseModel):
    fiscal_year: str | None = None
    pe: str | None = None
    ps: str | None = None
    pb: str | None = None


class StockValuation(BaseModel):
    """Valuation multiples placed in context.

    Pairs the company's trailing-twelve-month P/E with its sector and industry
    P/E (same exchange, same trading day) and its own multi-year P/E range, so
    a raw multiple reads as cheap or expensive relative to peers and to the
    company's own history. ``pe`` is taken from ``ratios-ttm`` rather than the
    quote because the quote's P/E field is unreliably populated.
    ``sector_pe``/``industry_pe`` are exchange-scoped — FMP publishes a separate
    figure per exchange — so ``exchange`` records which one was used and
    ``as_of_date`` the trading day it was sampled. ``pe_vs_sector`` /
    ``pe_vs_industry`` are decimal premiums (``0.20`` == 20% above the
    benchmark). Every field is null when FMP omits it, so the block degrades
    cleanly rather than failing the lookup.
    """

    pe: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    as_of_date: str | None = None

    sector_pe: str | None = None
    industry_pe: str | None = None
    pe_vs_sector: str | None = None
    pe_vs_industry: str | None = None

    pe_5y_low: str | None = None
    pe_5y_high: str | None = None
    pe_5y_median: str | None = None

    valuation_history: list[ValuationHistoryPoint] = Field(default_factory=list)


class QuarterlyEarning(BaseModel):
    report_date: str | None = None
    eps_actual: str | None = None
    eps_estimated: str | None = None
    eps_surprise_pct: str | None = None
    revenue_actual: str | None = None
    revenue_estimated: str | None = None
    revenue_surprise_pct: str | None = None
    price_move_pct: str | None = None


class StockEarnings(BaseModel):
    """Forward estimates, recent quarterly actuals, and typical post-earnings move.

    ``next_period_*`` are the nearest upcoming quarter from FMP analyst
    estimates. ``quarterly`` is the last reported quarters (newest first), each
    with a beat/miss surprise — ``(actual − estimated) / |estimated|`` as a
    decimal (``0.05`` == a 5% beat) — and, where bars are available, the stock's
    move around that report. FMP exposes no pre-/post-market timing, so
    ``price_move_pct`` and ``avg_post_earnings_move_pct`` use a fixed
    prev-close → first-session-on-or-after-report window. Every field is null
    when the data is missing, so the block degrades cleanly rather than failing
    the lookup.
    """

    next_period_end: str | None = None
    revenue_estimate_avg: str | None = None
    revenue_estimate_low: str | None = None
    revenue_estimate_high: str | None = None
    eps_estimate_avg: str | None = None
    eps_estimate_low: str | None = None
    eps_estimate_high: str | None = None
    num_analysts: int | None = None

    quarterly: list[QuarterlyEarning] = Field(default_factory=list)

    avg_post_earnings_move_pct: str | None = None
    events_measured: int | None = None


class StockInfoResponse(BaseModel):
    quote: StockQuote
    profile: StockProfile
    ratios: StockRatios
    financials: StockFinancials = Field(default_factory=StockFinancials)
    valuation: StockValuation = Field(default_factory=StockValuation)
    earnings: StockEarnings = Field(default_factory=StockEarnings)
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
