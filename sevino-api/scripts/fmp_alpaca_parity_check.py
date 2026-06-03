"""One-off FMP-vs-Alpaca bar parity check for the FMP_BARS_ENABLED rollout.

Not imported by the app. Run it where REAL market data is reachable — Alpaca
*sandbox* data is synthetic and makes the comparison meaningless, so use an
environment configured with production market-data credentials:

    cd sevino-api && uv run python scripts/fmp_alpaca_parity_check.py

For each basket symbol it fetches the same bars from FMP (the new path) and
Alpaca IEX (the current path) and reports the rollout-gating deltas: chart
%-change drift (O3), whether a partial current-day daily bar appears (O4),
last-close agreement, bar density, and premarket coverage for the digest's
overnight window. Flags mark disagreements beyond tolerance.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.fmp import FmpClient
from app.services.market_data import MarketDataService, _market_today

# Edit for your environment. Cover: liquid mega-cap, a liquid ETF, an index
# proxy, a recently-split volatile name, a thin small-cap, a recent IPO, and a
# delisted ticker — the cases most likely to expose a parity gap.
BASKET: list[tuple[str, str]] = [
    ("AAPL", "liquid mega-cap"),
    ("SPY", "index proxy / ETF"),
    ("QQQ", "liquid ETF"),
    ("NVDA", "recently-split, volatile"),
    # ("<THIN>", "thin small-cap"),
    # ("<IPO>", "recent IPO"),
    # ("<DELISTED>", "delisted"),
]

# (wire range, internal timeframe, days_back) — mirrors _CHART_PARAMS.
CHART_CASES: list[tuple[str, str, int]] = [
    ("1D", "5Min", 1),
    ("1W", "30Min", 7),
    ("1M", "1Hour", 30),
    ("3M", "1Day", 90),
    ("1Y", "1Day", 365),
    ("5Y", "1Week", 1825),
]

CLOSE_DRIFT_FLAG_PCT = Decimal("0.5")


class _NoopRedis:
    """MarketDataService requires a redis; the private bar methods never use it."""

    async def get(self, key: str) -> None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        return None


def _last_close(bars: list[dict]) -> Decimal | None:
    return Decimal(bars[-1]["close"]) if bars else None


def _change_pct(bars: list[dict]) -> Decimal | None:
    # Approximates the card's range %: (last - first) / first on the oldest
    # in-range bar. Good enough to surface the O3 first-bar-anchor drift.
    if len(bars) < 2:
        return None
    first = Decimal(bars[0]["close"])
    if first == 0:
        return None
    return (Decimal(bars[-1]["close"]) - first) / first * Decimal(100)


def _abs_pct_diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or a == 0:
        return None
    return abs(a - b) / abs(a) * Decimal(100)


async def _compare_charts(svc: MarketDataService) -> None:
    print("\n=== CHART PARITY (regular-session; FMP extended=False) ===")
    today = _market_today().isoformat()
    for symbol, label in BASKET:
        print(f"\n{symbol}  ({label})")
        for wire, timeframe, days_back in CHART_CASES:
            try:
                fmp = await svc._fmp_bars(symbol, timeframe, days_back, extended=False)
                alpaca = await svc._alpaca_bars(symbol, timeframe, days_back)
            except Exception as exc:
                print(f"  {wire:<4} ERROR {type(exc).__name__}: {exc}")
                continue

            flags: list[str] = []
            drift = _abs_pct_diff(_last_close(alpaca), _last_close(fmp))
            if drift is not None and drift > CLOSE_DRIFT_FLAG_PCT:
                flags.append(f"CLOSE Δ {drift:.2f}%")

            if timeframe in ("1Day", "1Week"):
                a_today = bool(alpaca) and alpaca[-1]["timestamp"][:10] == today
                f_today = bool(fmp) and fmp[-1]["timestamp"][:10] == today
                if a_today != f_today:
                    flags.append(f"PARTIAL-BAR alpaca={a_today} fmp={f_today}")

            change = ""
            chg_a, chg_f = _change_pct(alpaca), _change_pct(fmp)
            if chg_a is not None and chg_f is not None:
                change = f"  change% A={chg_a:+.2f} F={chg_f:+.2f}"

            print(
                f"  {wire:<4} bars A={len(alpaca):<5} F={len(fmp):<5}"
                f"{change}   {'  '.join(flags)}"
            )


async def _compare_overnight(svc: MarketDataService) -> None:
    print("\n=== DIGEST OVERNIGHT WINDOW (1Min; FMP extended=True) ===")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=2)
    for symbol, label in BASKET:
        try:
            fmp = await svc._fmp_bars(
                symbol, "1Min", start=start, end=now, extended=True
            )
            alpaca = await svc._alpaca_bars(symbol, "1Min", start=start, end=now)
        except Exception as exc:
            print(f"  {symbol:<6} ERROR {type(exc).__name__}: {exc}")
            continue
        note = "" if fmp else "  <- FMP empty (no extended-hours bars?)"
        print(f"  {symbol:<6} 1Min bars  A={len(alpaca):<6} F={len(fmp):<6}{note}  ({label})")


async def main() -> None:
    if settings.environment != "prod":
        print(
            f"WARNING environment={settings.environment!r}: Alpaca sandbox data "
            "is synthetic. Run against production market-data creds for a "
            "meaningful comparison.\n"
        )
    broker = AlpacaBrokerService()
    svc = MarketDataService(
        fmp=FmpClient(api_key=settings.fmp_api_key),
        alpaca_broker=broker,
        redis=_NoopRedis(),
        alpaca_data_url=settings.alpaca_data_base_url,
        alpaca_broker_url=settings.alpaca_base_url,
    )
    try:
        await _compare_charts(svc)
        await _compare_overnight(svc)
    finally:
        await svc.close()
        await broker.close()
    print(
        "\nDone. Flags = where FMP and Alpaca disagree beyond tolerance. "
        "Watch the FMP dashboard 'API Calls / Min' gauge while a full digest runs."
    )


if __name__ == "__main__":
    asyncio.run(main())
