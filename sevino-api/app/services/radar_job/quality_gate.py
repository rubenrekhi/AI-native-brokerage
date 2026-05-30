"""Static quality gate for the AI Radar universe (product spec §13.5).

The gate is the universe-wide beginner-protection filter: it runs
identically for every user, before any AI personalization, to keep penny
stocks, micro-caps, recent IPOs, leveraged/inverse products, and
policy-excluded names out of the candidate pool. The per-user *dynamic*
gate (risk-profile-aware) lives downstream in the LLM step.

Thresholds are deliberately conservative and centralized here so they can
be tuned in one place. They are policy, not law — CEO sign-off on
`MIN_MARKET_CAP_USD`, `EXCLUDED_INDUSTRIES`, and the ADR rule is tracked on
SEV-607 before launch.
"""

from datetime import date, timedelta

import structlog

from app.models.asset import Asset, AssetType

logger = structlog.get_logger(__name__)


MIN_MARKET_CAP_USD = 2_000_000_000  # mid-cap floor — top beginner-safety lever
MIN_SHARE_PRICE_USD = 5.00  # SEC penny-stock line
MIN_DAYS_SINCE_IPO = 365  # 12mo public history — avoids lockup volatility
MIN_AVG_DAILY_VOLUME_SHARES = 500_000  # liquidity floor

# Price and volume floors are policy here but NOT applied by this gate: the
# enriched `assets` table carries neither a share price nor an average
# volume (T1 enrichment stores sector/market_cap/ipo_date/asset_type/
# country only). They are enforced downstream at quote time, where the
# candidate sourcer (T3) has live market data. The market-cap floor is the
# dominant lever and stands in for both at the universe stage.

# `assets.exchange` carries Alpaca's venue codes (set by the asset sync,
# not FMP), so the allow-list is in Alpaca's vocabulary: NYSE, NASDAQ,
# AMEX (= NYSE American), ARCA (= NYSE Arca, where most broad-market ETFs
# list), and BATS (Cboe BZX). The rule exists to drop OTC / pink-sheet
# names — the only US venue intentionally left out.
ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"}

# Enrichment derives `asset_type` from FMP's isEtf/isFund flags as
# "stock" | "etf" | "fund" (see `app.models.asset.AssetType`). ETFs are
# admitted only when also in ALLOWED_ETFS; "fund" and anything unknown
# (including not-yet-enriched NULLs) are excluded.
ALLOWED_ASSET_TYPES = {AssetType.STOCK, AssetType.ETF}

ALLOWED_ETFS = {  # broad-market only — ETFs outside this set are excluded
    "SPY", "VOO", "QQQ", "VTI", "IWM",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
    "XLP", "XLU", "XLB", "XLRE", "XLC",
}

EXCLUDED_SYMBOLS = {  # leveraged/inverse — decay over time, unfit to hold
    "TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXU", "TNA", "TZA",
}

EXCLUDED_INDUSTRIES = {  # CEO policy placeholder — confirm scope (SEV-607)
    "Cannabis", "Adult Industry",
}

EXCLUDE_CHINESE_ADRS = True  # VIE-structure risk
CHINESE_ADR_COUNTRY = "CN"  # FMP profile returns ISO-2 country codes


class StaticQualityGate:
    """Filters the enriched asset universe to beginner-appropriate names.

    `filter` is pure over the rows it is handed — every threshold reads
    from the module constants above. Inputs are expected to come from
    `AssetRepository.list_eligible_for_radar` (enriched rows only); rows
    still missing enrichment after an attempt (FMP had no profile) keep
    NULL columns and are dropped by the market-cap / asset-type checks.
    """

    @classmethod
    def filter(cls, assets: list[Asset]) -> list[Asset]:
        ipo_cutoff = date.today() - timedelta(days=MIN_DAYS_SINCE_IPO)
        kept = [a for a in assets if cls._is_eligible(a, ipo_cutoff)]
        logger.info(
            "radar_quality_gate_filtered",
            total=len(assets),
            kept=len(kept),
        )
        return kept

    @staticmethod
    def _is_eligible(asset: Asset, ipo_cutoff: date) -> bool:
        symbol = (asset.symbol or "").upper()

        # A delisted/frozen name has no quality for a discovery surface and
        # can't be bought — drop it before any other signal.
        if not asset.tradeable:
            return False

        if symbol in EXCLUDED_SYMBOLS:
            return False

        if asset.asset_type not in ALLOWED_ASSET_TYPES:
            return False
        if asset.asset_type == AssetType.ETF and symbol not in ALLOWED_ETFS:
            return False

        if asset.exchange not in ALLOWED_EXCHANGES:
            return False

        if asset.market_cap is None or asset.market_cap < MIN_MARKET_CAP_USD:
            return False

        # Only *recent* IPOs are filtered. A missing ipo_date (an FMP data
        # gap on an otherwise-qualifying large cap) is not treated as
        # "too young" — recent IPOs always carry a known recent date.
        if asset.ipo_date is not None and asset.ipo_date > ipo_cutoff:
            return False

        if asset.industry in EXCLUDED_INDUSTRIES:
            return False

        if EXCLUDE_CHINESE_ADRS and asset.country == CHINESE_ADR_COUNTRY:
            return False

        return True
