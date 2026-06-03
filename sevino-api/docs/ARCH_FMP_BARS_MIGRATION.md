# Architecture: Historical Bars + Charts — Alpaca IEX → FMP (Ultimate)

**Status:** Authoritative design (final, post-adversarial-review) · **Date:** 2026-06-01
**Owner constraint:** *"We need to perform everything Alpaca does right now for this. We can't break anything with this refactor."*

This is the design of record for moving all historical price **bars** and **charts** off Alpaca's IEX feed onto FMP (Financial Modeling Prep, Ultimate plan). Alpaca **stays** for portfolio, trades, funding, account/KYC, and the market **clock**. The only intended *value* change is that FMP returns consolidated multi-exchange data instead of single-exchange IEX (more complete/accurate prices). Every other observable behavior — response shape, field types, sort order, timestamp format, timezone, empty-result handling, error semantics, caching, symbol handling, split-adjustment, extended-hours inclusion — is preserved, or, where it cannot be, is called out as an explicit **decision** rather than slipped in silently.

This version folds in three adversarial parity reviews (data-protocol, behavioral, operational). Every load-bearing code claim was re-verified against the working tree and the live FMP probe captures (`.context/fmp_probes/`); each is cited `file:line`. Two findings overturned a decision in the prior draft and are flagged **[CORRECTION]**. Invalid objections are listed in §12 with a one-line reason.

The spine is **§5, The Parity Matrix**.

---

## 1. Purpose & Scope

**In scope.** Exactly one private method produces every historical bar in the backend today: `MarketDataService._alpaca_bars` (`sevino-api/app/services/market_data.py:728-769`). Three entrypoints feed it — `get_chart` (REST + AI charts), `get_stock_bars` (the digest overnight/premarket move detector), `_fetch_earnings` (daily bars for post-earnings reactions). This refactor swaps the data source behind that single seam from Alpaca's `/v2/stocks/{symbol}/bars` (IEX feed) to FMP's `/historical-chart/{interval}` (intraday) and `/historical-price-eod/full` (daily), keeping the projected wire shape byte-identical so no consumer — REST schema, iOS decoder, AI tools, digest, earnings — changes behavior.

**Non-goals.** The market-open/closed **clock** (`_alpaca_clock`, `market_data.py:771-781`) and the Alpaca HTTP/OAuth token plumbing it shares stay on Alpaca; `get_market_status` and the quote-TTL selector depend on it. Portfolio/trades/funding/account/KYC stay on Alpaca. Quotes/profiles/fundamentals/news already come from FMP and are untouched.

**The one genuine product decision.** Whether user-facing charts keep showing pre-/after-market bars is a real behavior choice (it also changes a *displayed value*, not just sparkline density — see §8). It is decided in §8, not bundled silently into "parity."

---

## 2. Definition of Done / Acceptance Gates

Each gate is testable and must be green before `FMP_BARS_ENABLED` defaults to `true`.

1. **Schema-identical wire.** The projected bar is the exact 8-key dict `{timestamp, open, high, low, close, volume, vwap, trade_count}` with the same types (`open/high/low/close/vwap` = `str`; `volume`/`trade_count` = `int`; `timestamp` = `str`). `PriceBar` (`schemas/market_data.py:277-285`) validates without change; the iOS hand-mirrors `PriceBar` (`MarketDataModels.swift:122-141`) and `Bar` (`Block.swift:163-168`) need **zero** edits. Proven by the rewritten projection test asserting the full dict.
2. **Daily `timestamp` is full-ISO ET-midnight UTC, not date-only.** Daily/weekly `timestamp` is emitted as `"{date}T05:00:00Z"` (EST) / `"{date}T04:00:00Z"` (EDT) — the exact form Alpaca emits today (test fixtures: `T05:00:00Z`, `test_market_data_service.py:367-377`). This satisfies iOS `ISO8601Coder.parse`, earnings `[:10]`, the digest full-ISO branch, and the weekly `[:10]` resample simultaneously. **[CORRECTION — see D1.]** A unit test asserts daily `timestamp` parses on iOS-equivalent parsing and resolves to the correct ET session date under both EST and EDT.
3. **No consumer regression.** Every consumer in §3 reads the same keys/types/order it reads today: REST `ChartResponse` 200s with `bars:[]` on empty; the AI `StockCardBlock` still gets `{timestamp, close}` with a parseable `timestamp`; `change_for_range` still reads `bars[0]` as the *oldest* bar (`_performance.py:33`); `compute_earnings_reactions` still date-matches on `timestamp[:10]`; `digest/moves.py` still session-buckets correctly.
4. **DST-correct intraday timestamps.** Intraday FMP naive-ET timestamps are localized `America/New_York` → UTC → emitted with `Z`. A dedicated projection test asserts an EDT instant (`15:55 EDT → 19:55Z`) and an EST instant (`15:55 EST → 20:55Z`). No existing test catches a tz bug, so this test is mandatory and blocking.
5. **Digest correctness gate (curated, not "move_count vs IEX").** Parity is verified against a curated basket of real known overnight movers plus a zero-false-positive check on flat large-caps — *not* by comparing `move_count` to the IEX baseline (consolidated vs single-exchange will legitimately differ near thresholds). `move_count > 0` in logs is a liveness floor, not the parity criterion.
6. **Parity tolerances (structural exact, numbers tolerant, *plus* an intraday-change check).** Exact OHLCV *numbers* may differ (consolidated vs IEX) — flagged only when a daily close diverges by **> 0.5%**. Everything structural (shape, types, ordering, timestamp format, empty handling, error types, caching, symbol handling, split-adjustment) must be exact. **In addition** (closes review finding), if §8 lands on `extended=true` for charts, a 1W/1M `change_pct` parity check on a basket is required, because the daily-close-only tolerance would never catch a first-bar shift (see §8 / P12).
7. **Feature-flagged + reversible.** Routed behind `fmp_bars_enabled` (env `FMP_BARS_ENABLED`, default `false`). `_alpaca_bars` and `alpaca_data_url` stay alive **permanently** as the revert target (owner decision 2026-06-02); rollback is one env var. There is **no cleanup/deletion PR** — the flag and the Alpaca bar path are kept indefinitely.

---

## 3. Current-State Architecture

**The single seam.** `_alpaca_bars(symbol, timeframe, days_back=None, *, start=None, end=None, limit=10000)` (`market_data.py:728-769`) is the *only* place raw bars are projected. It:
- derives `start = now(utc) - days_back` when `start is None` (`:738-741`), else uses the caller's tz-aware datetime;
- builds path `/v2/stocks/{symbol}/bars` against `self._alpaca_data_url` (`:742`, = `settings.alpaca_data_base_url`, `config.py:120-124`);
- sends exactly six params `{timeframe, start=start.isoformat(), limit, adjustment="split", feed="iex", sort="asc"}`, adding `end=end.isoformat()` only if `end is not None` (`:743-752`) — **no session/`extended_hours` param**;
- GETs once via `_alpaca_get` (`:753`), reads `body.get("bars", []) or []` (`:756`, empty is never an error), and projects each raw `{t,o,h,l,c,v,vw,n}` bar to the 8-key dict (`:757-768`): OHLC+vwap as `str(...)`, `volume` as passthrough int (`bar["v"]`, `:764`), `trade_count` as `bar.get("n", 0)` (`:766`).

**Three entrypoints feed it:**
- `get_chart(symbol, timeframe)` (`market_data.py:216-241`) — validates `timeframe` against `_CHART_PARAMS` (7 wire ranges, `:57-65`), 422s on miss, checks Redis (`market:chart:{symbol}:{timeframe}`, `:224`), calls `_alpaca_bars(symbol, params["timeframe"], params["days_back"])` (no `end`, no `limit` override → `limit=10000`), wraps as `{symbol, timeframe, bars}`, and caches (60s intraday / 3600s daily, `:235-240`). **Empty results are cached too** (`:240` runs unconditionally).
- `get_stock_bars(symbol, *, timeframe, start, end=None, limit=10000)` (`market_data.py:243-260`) — the digest path; normalizes the symbol then calls `_alpaca_bars` directly (no Redis wrapper).
- `_fetch_earnings(symbol)` (`market_data.py:393-427`) — calls `_alpaca_bars(symbol, "1Day", 730)` inside `asyncio.gather(..., return_exceptions=True)`; any exception degrades reaction fields to `[]`.

**Consumers of the projected dict:**
- **REST** `GET /chart` → `ChartResponse{symbol, timeframe:ChartTimeframe, bars:[PriceBar]}` (`schemas/market_data.py:277-291`). `PriceBar` requires all 8 fields, non-optional. iOS mirrors it (`MarketDataModels.swift:122-141`) as a wire contract; **no live SwiftUI view calls `getChart` today** — the REST-decode risk is latent for that path.
- **AI inline chart (LIVE).** `bars_from_chart` (`_performance.py:11-15`) builds `Bar(t=bar["timestamp"], c=float(bar["close"]))` — it copies `timestamp` **verbatim** into `Bar.t`. `change_for_range` (`:18-38`) reads only `bar["timestamp"]`/`bar["close"]` and **depends on `bars[0]` being the oldest** for per-range change (`:33`, `first_close = bars[0].c`). The live render is `SingleStockCard.swift`: `chartDates = currentBars.map { ISO8601Coder.parse($0.t) ?? .now }` (`:44-45`). This is the path that makes the daily-timestamp choice **live**, not latent (see D1).
- **digest** `detect_overnight_moves` (`digest/moves.py`) — `_detect_symbol` (`:140-215`) fetches `1Day` (10-day lookback, `limit=10`) → `_latest_completed_daily_bar` filters `_bar_session_date(bar) < today_et` (`:292-297`) → derives `window_start = _regular_close_utc(_bar_session_date(prev_bar))` (16:00 ET of the prev session, `:172,361-364`) → fetches `1Min` from that window to now (`:173-180`) → `_latest_bar_with_close` takes the max-timestamp bar (`:196,300-306`). Timestamps parse via `_parse_bar_timestamp` (date-only len==10 → ET-midnight; full-ISO with `Z`; naive → UTC; `:330-358`); session bucketing is `.astimezone(ET).date()` (`:319-323`). **Depends on extended-hours 1Min bars existing** (`:196-215`).
- **earnings** `compute_earnings_reactions` (`fmp.py:1032-1071`) — reads `bar["timestamp"]` via `_parse_iso_date` (`value[:10]`, `:1009-1016`) and `bar["close"]`; re-sorts internally (order-tolerant); matches FMP `report_date` against the date part.

**Data flow (today):**
```
get_chart ─┐
get_stock_bars (digest) ─┼─► _alpaca_bars ─► GET data.alpaca.markets/v2/stocks/{sym}/bars
_fetch_earnings ─┘          (feed=iex, adjustment=split, sort=asc, limit=10000)
                                 │  via _alpaca_get → _alpaca_headers → broker.access_token()
                                 ▼
                            8-key projected dict  ─► REST PriceBar / AI Bar (LIVE) / digest / earnings

_alpaca_clock ─► get_market_status ─► REST /market/status + quote-TTL   [STAYS ON ALPACA]
   (shares _alpaca_get / _alpaca_headers / _alpaca_client / token cache)
```

---

## 4. Target-State Architecture

A new normalization layer in `FmpClient` produces bars; the seam method `_fmp_bars` replaces `_alpaca_bars` behind the feature flag.

```
                          fmp_bars_enabled?
get_chart ─────────────┐   ┌── false ──► _alpaca_bars ──► Alpaca IEX   [kept permanently — revert target]
get_stock_bars (digest)├──►┤
_fetch_earnings ───────┘   └── true ───► _fmp_bars (dispatcher)
                                              │  timeframe routing
                              ┌───────────────┴────────────────┐
                  intraday {1Min,5Min,15Min,30Min,1Hour,4Hour}   EOD {1Day,1Week}
                              │                                  │
              FmpClient.historical_chart                FmpClient.historical_eod
              (/historical-chart/{interval},            (/historical-price-eod/full,
               extended per call-site §8)                split-adjusted)
                              │                                  │
                              ▼                                  ▼
                   project_bars(rows, intraday=True)   project_bars(rows, intraday=False)
                              │                                  │ (+ _resample_weekly if 1Week)
                              └──────────────► 8-key projected dict ◄────────┘
                                          (byte-identical to today)

FmpClient._request: connection→MarketDataUnavailableError, non-200→MarketDataUpstreamError, 402→MarketDataError
                    (same exception types _alpaca_get raises; auth = apikey query param, no bearer)

_alpaca_clock ─► get_market_status / quote-TTL    [UNCHANGED — stays on Alpaca; token plumbing preserved]
```

**The feature-flag dual-path** is the only branch:
```python
bars = (
    await self._fmp_bars(symbol, timeframe, days_back, start=start, end=end, extended=extended)
    if settings.fmp_bars_enabled
    else await self._alpaca_bars(symbol, timeframe, days_back, start=start, end=end, limit=limit)
)
```
`extended` is computed per call-site (§8); `limit` is a no-op under FMP (P22) but stays on the signature.

**What stays (must not be removed while the flag exists; clock plumbing stays forever):** `_alpaca_clock`, `_alpaca_get`, `_alpaca_headers`, `self._alpaca_client`, `self._alpaca_broker`/`access_token()`, the OAuth token cache, `self._alpaca_broker_url` (= `settings.alpaca_base_url`). Nothing is deleted — the flag keeps both paths live, so `self._alpaca_data_url` stays in use by `_alpaca_bars` indefinitely. `test_close_closes_both_clients` pins that `self._alpaca_client` is still closed on shutdown.

---

## 5. THE PARITY MATRIX

The spine. Verdicts: **IDENTICAL** (byte/semantic match), **EQUIVALENT** (different mechanism, same observable result), **INTENTIONAL-CHANGE** (a called-out decision), **UNPROVEN** (parity expected but the evidence is inference, not a probe — gates a PR). Every Alpaca behavior from the inventory is here.

| # | Dimension | Alpaca today (cite) | FMP design reproduction | Verdict | Residual risk |
|---|---|---|---|---|---|
| **P1** | **Projected dict — keys** | 8 keys `{timestamp, open, high, low, close, volume, vwap, trade_count}` (`market_data.py:757-768`) | `project_bars` emits the same 8 keys for intraday and daily | **IDENTICAL** | None — pinned by rewritten projection test + `PriceBar` schema |
| **P2a** | **Field types — OHLC / vwap / trade_count** | OHLC+vwap = `str(...)`; `trade_count` = int (`:760-766`) | `str(raw[...])` for OHLC; `vwap` str; `trade_count` int | **IDENTICAL** | None |
| **P2b** | **Field type — volume** | passthrough int `bar["v"]` (`:764`); Alpaca volume is already int | `int_or_zero(raw["volume"])` (`fmp.py:42`, does `int(value)`). FMP intraday volume is **mixed int/float** within one response, e.g. `2667385.7599…` (probe `chart_5min_aapl.json`) → truncates to `2667385` | **EQUIVALENT** | **[CORRECTION]** Not IDENTICAL for intraday: FMP's fractional consolidated-aggregate volume is truncated toward zero. Schema/iOS require `int`, so coercion is *required* (an uncoerced float would 500 the REST `int` field and crash iOS `Int` decode). No consumer does bar-volume math (digest reads close only; card stats use the quote, not bar volume), so the truncated value is invisible — but it is a real value change, hence EQUIVALENT |
| **P3** | **`vwap` presence** | always present; `str(bar.get("vw","0"))` → real IEX vwap on intraday, "0" only when missing (`:765`) | Daily: `str(raw["vwap"])` (FMP daily has real vwap). Intraday: synthesized `"0"` (FMP intraday has no vwap) | **EQUIVALENT** | **[CORRECTION]** Intraday is a *real-value → "0" drop*, not "matches Alpaca's missing-key fallback" — IEX usually carried a real intraday `vw`. Justified only by **no consumer reading vwap** (`change_for_range`/digest/earnings read close+timestamp only). Daily is a real value, IDENTICAL in spirit |
| **P4** | **`trade_count` presence** | `bar.get("n", 0)`, int (`:766`) | synthesized `0` everywhere (FMP carries no `n`) | **EQUIVALENT** | None — no consumer reads it; dropping it would be a breaking schema/iOS change for zero benefit |
| **P5** | **Timestamp format — intraday** | `bar["t"]` = UTC ISO-8601 with `Z` (`:759`) | FMP intraday `date` = naive ET `"2026-06-01 15:55:00"` → localize `America/New_York` → `.astimezone(UTC)` → ISO with `Z` | **IDENTICAL** (after transform) | **CRITICAL if skipped.** Passthrough = 4–5h shift → digest buckets the wrong session and picks the wrong "latest" bar. Mandatory DST test (DoD #4). FMP intraday has no fractional seconds, so `Z`-second precision parses cleanly on iOS |
| **P6** | **Timestamp format — daily/weekly** | Alpaca daily `t` = **full-ISO ET-midnight UTC**: `"2026-01-28T05:00:00Z"` (EST) / `…T04:00:00Z` (EDT) — verified by repo fixtures (`test_market_data_service.py:367-377`), NOT `T00:00:00Z`, NOT date-only | FMP daily `date` = date-only `"2026-06-01"` → re-emit as **ET-midnight UTC** `datetime.combine(d, midnight, ET).astimezone(UTC)` with `Z` | **IDENTICAL** (after transform) | **[CORRECTION] — see D1.** Emitting date-only verbatim would break the **live** AI card (PB1) and risk digest drift; emitting `T00:00:00Z` would roll the digest session date back one day (verified). ET-midnight-UTC is the unique form that satisfies all four consumers |
| **P7** | **Sort order** | `sort="asc"` → oldest-first (`:749`) | FMP is **newest-first** on both endpoints (probes: EOD `2026-06-01`→`2021-06-02`; 5min `15:55`→`09:30`) → `project_bars` does `reversed(rows)` | **IDENTICAL** (after reverse) | `change_for_range` reads `bars[0]` as oldest (`_performance.py:33`); sparkline renders in array order. Un-reversed = wrong sign / backward chart |
| **P8** | **Empty result** | `body.get("bars",[]) or []` → `[]`, **never raises** (`:756`) | FMP returns `200 + []` for invalid/thin symbols (probe). New bar methods `return data or []`; projection over `[]` is `[]` | **IDENTICAL** | **High if mishandled.** See **D2** — bar methods must NOT copy `quote()`'s raise-on-empty. Empty must still reach `_cache_set` (`market_data.py:240`) |
| **P9** | **Daily split-adjustment** | `adjustment="split"` (`:747`) | `/historical-price-eod/full` is split-adjusted (NVDA 2024-06-10 10:1 → surrounding closes ~$120, probe `eod_nvda_split.json`) | **IDENTICAL** | None. Must use `full`. **Never** `/non-split-adjusted` — it uses `adjOpen/adjHigh/adjLow/adjClose` keys with **no `open/close/vwap`** (probe `eod_nvda_nonsplit.json`), so `project_bars` would `KeyError`/500 (G12) |
| **P10** | **Intraday split-adjustment** | `adjustment="split"` applies to intraday too | FMP `/historical-chart/` is split-adjusted — **PROBE-CONFIRMED (2026-06-01)**: NVDA 1hour bars straddling the 2024-06-10 10:1 split read ~$117–$127 across all dates incl. pre-split (back-adjusted), not ~$1200 (probe `chart_1hour_nvda_split.json`). FMP 1hour history also reaches ≥2yr, far beyond the ≤30d charts need | **IDENTICAL** | None — O1 closed |
| **P11** | **Extended hours — digest 1Min** | no session param → IEX default **includes** pre/after-market; digest relies on them (`moves.py:196-215`) | `historical_chart(..., extended=True)` for the digest 1Min leg (FMP default is regular-only; `extended=true` → 04:00–19:59 ET, probe) | **IDENTICAL** (after `extended=true`) | **CRITICAL.** Without it, the overnight window has zero bars → `_latest_bar_with_close` None → `_flat_move` → every move flat. `extended = timeframe in _INTRADAY_BAR_TIMEFRAMES`, **always true** for the digest 1Min leg (non-negotiable) |
| **P12** | **Extended hours — charts** | same default IEX path → charts **include** extended bars today, *where IEX had a print* (IEX premarket coverage is sparse per symbol) | Decision point: `extended=true` (parity-faithful) vs `extended=false`. See §8 | **INTENTIONAL-CHANGE / DECISION** | **Recommended `extended=true`** (§8). **[CORRECTION] blast radius:** for 1W (`30Min`) / 1M (`1Hour`), `change_for_range` keys off `bars[0]` (`_performance.py:33`), so a 04:00 first bar vs a 09:30 first bar **changes the displayed `change_pct`**. FMP's dense premarket vs IEX's sparse premarket means this can shift even under `extended=true`. DoD #6 adds an intraday-change parity check; the DoD #5 daily-close tolerance does not catch it. 1D is immune (uses daily change, `_performance.py:29-30`) |
| **P13** | **Error: connection failure** | `httpx.HTTPError` → `MarketDataUnavailableError` (`:795-802`) | `_request`: `httpx.HTTPError` → `MarketDataUnavailableError` (`fmp.py:201-213`) | **IDENTICAL** | None |
| **P14** | **Error: non-200** | status≠200 → `MarketDataUpstreamError(status_code=...)` (`:804-816`) | `_request`: non-200 (≠402) → `MarketDataUpstreamError(status_code=...)` (`fmp.py:259`) | **IDENTICAL** | None. 429 lands here and is already caught by consumers |
| **P15** | **Error: token failure** | `access_token()` fail → `MarketDataUnavailableError` (`_alpaca_headers:721-725`) | FMP needs no token (apikey query param) → this failure mode **disappears for bars** | **EQUIVALENT** (strictly fewer failures) | None. The clock path keeps the token alive so `_alpaca_headers` is still exercised by `get_market_status` |
| **P16** | **Error: symbol not in tier** | N/A (Alpaca had no per-symbol tier gate) | FMP 402 → `MarketDataError` (`fmp.py:224-238`) | **INTENTIONAL-CHANGE** (new branch) | Digest must **NOT** add a blanket `except MarketDataError: return []` — it only catches `MarketDataUnavailableError`/`MarketDataUpstreamError` (`moves.py:149,181`), so a 402 propagates and degrades via `prev_bar is None → _empty_move` / earnings `gather`, surfacing the coverage gap instead of masking it |
| **P17** | **Global error → HTTP** | Upstream→502, Unavailable→503, MarketDataError→404, InvalidInput→422 (`exceptions.py:316-337`) | Unchanged — same exception types reach the same handlers | **IDENTICAL** | None — iOS `APIError` codes/statuses preserved |
| **P18** | **Caching keys** | `market:chart:{symbol}:{timeframe}` (wire range) (`:224`); status `market:status` | Unchanged — built from the *wire* range, not the internal token | **IDENTICAL** | None |
| **P19** | **Caching TTLs** | 60s intraday (`5Min/30Min/1Hour`), 3600s daily/weekly (`:103-104,235-239`); empty cached | Unchanged. TTL switch reads `_INTRADAY_TTL_TIMEFRAMES` (charts use only `5Min/30Min/1Hour/1Day/1Week`), distinct from `_INTRADAY_BAR_TIMEFRAMES` used for dispatch | **IDENTICAL** | **[CORRECTION]** Split the one overloaded constant into two (see §6.3 / m-split) so adding `1Min/15Min/4Hour` to dispatch can never silently change a chart's TTL. Pinned by `test_intraday_timeframe_uses_short_ttl` / `test_daily_timeframe_uses_long_ttl` |
| **P20** | **Symbol normalization** | `strip().upper()` + `_SYMBOL_RE`; raises `MarketDataInvalidInputError` (`:925-939`) | Unchanged — applied at the same public entrypoints before the FMP `symbol=` param and cache key | **IDENTICAL** | None — FMP receives the same canonical symbol |
| **P21** | **Pagination** | single GET; `next_page_token` never read (`:753-769`) | single FMP request per call; `from`/`to` returns the full `[from,now]` window (probe: `from`-only == `from`+`to`, byte-identical 35 rows) | **IDENTICAL** | None — all windows single-response |
| **P22** | **`limit` / row caps** | `limit=10000` row cap; never binding at current window sizes (`:746`) | FMP has no `limit` param; returns the full window. Signature keeps `limit` for protocol/cache-key parity → **no-op** | **EQUIVALENT** | Low. Document the no-op so a future caller doesn't assume `limit` truncates. Was effectively a no-op under Alpaca too |
| **P23** | **Window derivation** | `start=now-days_back` if no `start`; `end` omitted unless passed; chart/earnings no `end` (`:738-741,751`) | `_fmp_bars` mirrors it; defensively sets `end=now`; converts to ET `.date()` for FMP `from`/`to` | **EQUIVALENT** | Low. FMP `from`/`to` are date-granular vs Alpaca's full datetime. The digest sub-day 1Min window passes a 16:00-ET `start`, but FMP `from=<date>` returns the **whole prior session from 04:00 ET**. Safe for the *current* consumer (`_latest_bar_with_close` reads only the max-timestamp bar, `moves.py:196`); the lower-bound divergence is documented and pinned by the digest test so a future "read first overnight bar" change can't silently regress (M2) |
| **P24** | **Timeframe validation** | `get_chart` 422s on range ∉ 7 keys (`:218-222`); `get_stock_bars`/earnings pass raw tokens unchecked | `get_chart` keeps its `_CHART_PARAMS` gate; `_fmp_bars` raises `MarketDataInvalidInputError` for any token ∉ `{1Min,5Min,15Min,30Min,1Hour,4Hour,1Day,1Week}` | **IDENTICAL** | None |
| **P25** | **Rate limits** | Alpaca: 1 call/symbol/timeframe | FMP: 1 call/symbol/timeframe; digest fan-out ×N symbols, deduped by `RunScopedStockBarsProvider` | **EQUIVALENT** | **OPEN (O2).** FMP Ultimate per-minute cap unconfirmed; **blocks PR 3**. 429→Upstream already caught; add `Retry-After` backoff + concurrency bound if it appears |
| **P26** | **Weekly (5Y / 1Week)** | Alpaca native `1Week` bars (`_CHART_PARAMS:64`) | No FMP weekly endpoint → fetch daily `full`, resample client-side by ISO `(year, week)` | **EQUIVALENT** | Med. ISO-week boundary may differ from Alpaca's anchor, but **5Y has no AI consumer** (`PERFORMANCE_RANGES` stops at 1Y, `_performance.py:8`) — only the live REST sparkline. Correctness > exact-match |
| **P27** | **Daily partial (today) bar** | unverified whether Alpaca daily intra-session returns a partial current-day bar | FMP `/historical-price-eod/full` **does** return today's in-progress bar intra-session (probe `eod_full_aapl.json` newest row = `2026-06-01`, the probe date) | **UNPROVEN (charts) / IDENTICAL (digest+earnings)** | **[NEW — review finding M1].** Digest is immune (`_latest_completed_daily_bar` filters `session_date < today_et`, `moves.py:296`); earnings is immune (730-day historical window). **Charts are not:** a 3M/6M/1Y daily chart could gain a trailing partial point vs today. Probe Alpaca's intra-session daily behavior before PR 3; if Alpaca omits today, bound chart daily `to = yesterday(ET)` *or* accept+document the trailing point (§11 O5) |
| **P28** | **Clock coupling** | `_alpaca_clock` + shared token plumbing feed `get_market_status` + quote-TTL (`:771-781,676-690`) | **Unchanged** — stays on Alpaca; nothing removed from the clock path | **IDENTICAL** | High if accidentally removed. Explicit keep-list (§9); clock tests stay green |

### Decisions embedded in the matrix

**D1 — Daily/weekly `timestamp` emitted as ET-midnight UTC, NOT date-only and NOT `T00:00:00Z`. [CORRECTION to the prior draft.]**

The prior draft emitted FMP's date-only `"2026-06-01"` verbatim, classifying the iOS impact as "latent." All three reviews flagged this; verification confirms it is wrong on two counts:

1. **It is a LIVE regression, not latent.** The live AI stock card builds `Bar(t=bar["timestamp"], …)` verbatim (`_performance.py:13`) and renders `chartDates = currentBars.map { ISO8601Coder.parse($0.t) ?? .now }` (`SingleStockCard.swift:44-45`). `ISO8601Coder.parse` accepts only `.withInternetDateTime` (± fractional) (`ISO8601Coder.swift:11-12,19-29`), so a date-only string returns `nil` → `.now`. Today the 3M/6M/1Y daily ranges carry Alpaca's full-ISO `T05:00:00Z`/`T04:00:00Z` (repo fixtures, `test_market_data_service.py:367-377`), which parses fine. Switching to date-only collapses **every** daily/weekly scrub-date label to "now." The line geometry is index-based (`SingleStockCard.swift:31-37`), so the curve still renders — but the scrub tooltip is an observable break, which the owner's mandate forbids.

2. **The prior draft reasoned from the wrong Alpaca anchor.** It asserted Alpaca daily = `T00:00:00Z`. The repo's own fixtures model it as `T05:00:00Z` (midnight ET in UTC). This matters because the digest does tz math: `_bar_session_date` = `_parse_bar_timestamp(bar).astimezone(ET).date()` (`moves.py:319-323,330-358`). Verified across EST/EDT:

   | Daily encoding | digest `_bar_session_date` for session `D` | earnings `[:10]` | iOS `parse` |
   |---|---|---|---|
   | date-only `"D"` | **D** (len==10 branch → ET-midnight) | D ✓ | **nil ✗** |
   | `"D T00:00:00Z"` | **D−1** ✗ (UTC midnight is prev-day ET) | D ✓ | Date ✓ |
   | **`"D T05:00:00Z"`/`T04:00:00Z` (ET-midnight UTC)** | **D ✓** | **D ✓** | **Date ✓** |

   Only the ET-midnight-UTC form satisfies all four consumers (iOS parse, earnings `[:10]`, digest full-ISO branch, weekly `[:10]`). A naive "append `T00:00:00Z`" fix would *reintroduce* a one-day digest rollback in `window_start = _regular_close_utc(_bar_session_date(prev_bar))` (`moves.py:172`).

   **Resolution (final).** `project_bars(intraday=False)` emits `timestamp = datetime.combine(date.fromisoformat(raw["date"]), time.min, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat().replace("+00:00","Z")`. This is **byte-identical to what Alpaca emits today** and is strictly safer than either alternative. It removes the prior draft's "forward-compat trigger" entirely. (Optional pre-PR-1 confidence step: probe one live Alpaca `1Day` bar to re-confirm the anchor; the repo fixtures already make this the high-confidence choice.)

**D2 — Empty result returns `[]`, never raises (P8). [CORRECTION to `FINDINGS.md:46`.]** `FINDINGS.md:46` advises new bar methods should "raise `MarketDataError`, matching `FmpClient.quote`." **That is wrong for the bar path** and is overruled. `quote()`/`profile()` raise on empty because a missing quote is a hard failure; but `_alpaca_bars` maps empty bars to `[]` (`:756`), and every bar consumer depends on it: `get_chart` caches `{"bars":[]}` and returns 200 (`:240`); `display_stock_card` suppresses the card only on an *exception* of the initial range (`display_stock_card.py:169-174`), not on empty; the digest degrades empty to `_empty_move`/`_flat_move`; earnings degrades empty to no reaction rows. Therefore `historical_chart`/`historical_eod` end with `return data or []` and **must not** add `if not data: raise`.

---

## 6. Component Specs

### 6.1 `FmpClient` bar methods (`app/services/fmp.py`)

Both route through the existing `FmpClient._request` (`fmp.py:186-260`), verified to map connection→`MarketDataUnavailableError` (`:213`), 402→`MarketDataError` (`:235`), other non-200→`MarketDataUpstreamError` (`:259`), and attach `apikey` as a query param (no bearer). Pass `symbol_for_errors=symbol` so a 402 log carries the symbol.

```python
async def historical_chart(
    self, symbol: str, interval: str, *,
    start: date | None = None, end: date | None = None, extended: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"symbol": symbol}
    if start: params["from"] = start.isoformat()
    if end:   params["to"]   = end.isoformat()
    if extended: params["extended"] = "true"
    data = await self._request(
        f"/historical-chart/{interval}", params, symbol_for_errors=symbol
    )
    return data or []   # empty => [], NEVER raise (D2)

async def historical_eod(
    self, symbol: str, *, start: date | None = None, end: date | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"symbol": symbol}
    if start: params["from"] = start.isoformat()
    if end:   params["to"]   = end.isoformat()
    data = await self._request(
        "/historical-price-eod/full", params, symbol_for_errors=symbol
    )
    return data or []   # empty => [], NEVER raise (D2)
```

- `extended` is a parameter of `historical_chart` **only**, set by the seam per call-site (§8). Daily/`historical_eod` has no session concept.
- Daily uses **`full`** (the only EOD variant carrying `open/close/vwap`, split-adjusted; P9/G12). Never `/non-split-adjusted`.

### 6.2 `project_bars` — the single normalization (`app/services/fmp.py`)

Emits the exact 8-key dict. Requires **`from decimal import Decimal`** and **`from zoneinfo import ZoneInfo`** added to `fmp.py`'s imports (**[CORRECTION]** — neither is currently imported; `fmp.py:1` imports only `date, datetime, timezone`). Reuses `int_or_zero` (`fmp.py:40-44`).

```python
def project_bars(rows: list[dict[str, Any]], *, intraday: bool) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for raw in reversed(rows):                       # P7: FMP newest-first → ascending
        timestamp = (
            _intraday_timestamp(raw["date"]) if intraday   # P5: naive-ET → UTC Z
            else _daily_timestamp(raw["date"])             # P6: date-only → ET-midnight UTC Z (D1)
        )
        bars.append({
            "timestamp": timestamp,
            "open":  str(raw["open"]),  "high": str(raw["high"]),
            "low":   str(raw["low"]),   "close": str(raw["close"]),
            "volume": int_or_zero(raw.get("volume")),               # P2b (FMP float → int, truncates)
            "vwap":  "0" if intraday else str(raw.get("vwap", "0")), # P3
            "trade_count": 0,                                        # P4
        })
    return bars
```

**Timestamp helpers (each ties to a parity row):**
```python
_ET = ZoneInfo("America/New_York")

def _intraday_timestamp(naive_et: str) -> str:                 # P5
    dt = datetime.strptime(naive_et, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_ET)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _daily_timestamp(date_only: str) -> str:                   # P6 / D1
    d = date.fromisoformat(date_only)
    dt = datetime.combine(d, time.min, tzinfo=_ET)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
```
- **P5 (intraday tz).** Per-instant DST via `ZoneInfo` (no fixed offset). The Nov fall-back fold (01:00–02:00 ET ambiguity) is irrelevant — equity sessions, even extended 04:00–20:00, never include that window.
- **P6 (daily tz).** ET-midnight → UTC, emitting `…T05:00:00Z` (EST) / `…T04:00:00Z` (EDT) — byte-identical to Alpaca, parseable by iOS, `[:10]`-stable for earnings/weekly, same-day for the digest (D1).
- **P2b/P3/P4.** `int_or_zero(volume)` (FMP intraday volume is float/mixed); `vwap="0"` intraday, real `vwap` daily; `trade_count=0` always.
- **P7.** `reversed(rows)` — FMP is newest-first; consumers assume oldest-first.

### 6.3 `_fmp_bars` dispatcher + timeframe routing (`MarketDataService`)

Replaces `_alpaca_bars` behind the flag. **[CORRECTION — m-split]** the single overloaded `_INTRADAY_TIMEFRAMES` (`market_data.py:69`) becomes **two** frozensets so the TTL contract and the dispatch contract can't drift:
- `_INTRADAY_TTL_TIMEFRAMES = {"5Min","30Min","1Hour"}` — used by the `get_chart` 60s/3600s TTL switch (the *only* timeframes a chart routes through). Unchanged from today.
- `_INTRADAY_BAR_TIMEFRAMES = {"1Min","5Min","15Min","30Min","1Hour","4Hour"}` — used by `_fmp_bars` to choose intraday vs EOD and to set `extended`.

```python
_FMP_INTERVAL = {"1Min":"1min","5Min":"5min","15Min":"15min",
                 "30Min":"30min","1Hour":"1hour","4Hour":"4hour"}

async def _fmp_bars(self, symbol, timeframe, days_back=None, *,
                    start=None, end=None, extended=False):
    now = datetime.now(timezone.utc)
    if start is None:
        if days_back is None:
            raise ValueError("days_back or start is required")  # P23, matches _alpaca_bars
        start = now - timedelta(days=days_back)
    if end is None:
        end = now                                  # defensive; FMP honors from-only as [from,now]
    start_d = start.astimezone(_MARKET_TZ).date()  # FMP from/to are date-granular
    end_d   = end.astimezone(_MARKET_TZ).date()
    if timeframe in _INTRADAY_BAR_TIMEFRAMES:
        rows = await self._fmp.historical_chart(
            symbol, _FMP_INTERVAL[timeframe], start=start_d, end=end_d, extended=extended)
        return project_bars(rows, intraday=True)
    if timeframe in ("1Day", "1Week"):
        rows  = await self._fmp.historical_eod(symbol, start=start_d, end=end_d)
        daily = project_bars(rows, intraday=False)
        return _resample_weekly(daily) if timeframe == "1Week" else daily
    raise MarketDataInvalidInputError(f"Unsupported bar timeframe: {timeframe}", symbol=symbol)
```

`extended` is supplied by the caller and computed at each call-site as `extended = timeframe in _INTRADAY_BAR_TIMEFRAMES` (digest 1Min → True always, P11; charts → §8 decision).

**Routing table (FINAL):**

| Wire range | Internal tf | days_back | FMP endpoint / interval | extended | Window |
|---|---|---|---|---|---|
| `1D` | `5Min` | 1 | `/historical-chart/5min` | §8 (rec. true) | from=yesterday(ET), to=now |
| `1W` | `30Min` | 7 | `/historical-chart/30min` | §8 (rec. true) | from/to |
| `1M` | `1Hour` | 30 | `/historical-chart/1hour` | §8 (rec. true) | from/to |
| `3M` | `1Day` | 90 | `/historical-price-eod/full` | n/a | from/to |
| `6M` | `1Day` | 180 | `/historical-price-eod/full` | n/a | from/to |
| `1Y` | `1Day` | 365 | `/historical-price-eod/full` | n/a | from/to |
| `5Y` | `1Week` | 1825 | `/historical-price-eod/full` + `_resample_weekly` | n/a | from/to |
| digest `1Min` | `1Min` | — | `/historical-chart/1min` | **TRUE** | digest start/end |
| digest `1Day` | `1Day` | — | `/historical-price-eod/full` | n/a | digest start/end |
| earnings `1Day` | `1Day` | 730 | `/historical-price-eod/full` | n/a | from/to |

### 6.4 `_resample_weekly` (`app/services/fmp.py`)

Daily `full` → weekly, client-side (P26). Input is the already-projected, ascending daily list. Uses `Decimal` (now imported per §6.2) and `date` (already imported, `fmp.py:1`).

```python
def _resample_weekly(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], list[dict]] = {}
    for bar in daily:                                  # ascending in, ascending out
        iso_year, iso_week, _ = date.fromisoformat(bar["timestamp"][:10]).isocalendar()
        buckets.setdefault((iso_year, iso_week), []).append(bar)
    out = []
    for key in sorted(buckets):
        wk = buckets[key]
        out.append({
            "timestamp": wk[-1]["timestamp"],          # week's last session, full-ISO ET-midnight (P6)
            "open":  wk[0]["open"],
            "high":  str(max(Decimal(b["high"]) for b in wk)),
            "low":   str(min(Decimal(b["low"])  for b in wk)),
            "close": wk[-1]["close"],
            "volume": sum(b["volume"] for b in wk),
            "vwap": "0", "trade_count": 0,
        })
    return out
```
`bar["timestamp"][:10]` slices the full-ISO `…T05:00:00Z` to the date — still correct under D1. Keyed by ISO `(year, week)` so week 1/53 boundaries are deterministic. ≤ ~260 weekly bars over 5Y. No AI consumer; correctness (valid ascending `PriceBar`s, no exceptions) is the bar.

### 6.5 Error mapping

No new mapping code — the FMP path inherits `_request`'s mapping, which produces the *same exception types* as `_alpaca_get` (P13/P14). The only deltas, both intentional and benign: the token-failure path disappears for bars (P15), and 402→`MarketDataError` is a new branch the digest must not swallow (P16). Global handlers (`exceptions.py:316-337`) are untouched (P17).

### 6.6 Caching (unchanged)

`get_chart` keeps `market:chart:{symbol}:{timeframe}` keyed on the wire range, the 60s/3600s TTL switch on `_INTRADAY_TTL_TIMEFRAMES`, and **caches empty results** (P18/P19). `get_stock_bars` remains uncached (deduped by `RunScopedStockBarsProvider`). Earnings bars remain folded into the 12h `market:fundamentals:{symbol}` blob. Redis errors stay non-fatal. **Implementation note (review m-cache):** PR 2 swaps only the `_alpaca_bars(...)` call expression inside `get_chart`; lines `:234-240` (wrap + `_cache_set`) are left byte-for-byte intact so empty-caching cannot regress.

---

## 7. Sequence Flows

**Flow A — REST/AI chart (`get_chart`, e.g. 1M).**
1. `get_chart(symbol, "1M")` → `_normalize_symbol` (P20) → `_CHART_PARAMS["1M"]` = `(1Hour, 30)` (P24).
2. Redis check `market:chart:{symbol}:1M`; hit returns cached dict verbatim (P18).
3. Miss → seam `_fmp_bars(symbol, "1Hour", 30, extended=<§8: true>)`.
4. `1Hour ∈ _INTRADAY_BAR_TIMEFRAMES` → `historical_chart(symbol,"1hour", from=now-30d(ET), to=now(ET), extended=true)`.
5. `project_bars(rows, intraday=True)`: reversed → ascending (P7), ET→UTC `Z` timestamps (P5), `vwap="0"`/`trade_count=0` (P3/P4), `int_or_zero(volume)` (P2b).
6. Wrap `{symbol, timeframe:"1M", bars}`, `_cache_set` 60s (intraday TTL, P19), return.
7. Consumers: REST validates `PriceBar` (8 keys/types match); AI `Bar.t` parses on iOS (full-ISO); `change_for_range` reads `bars[0]` (oldest after reverse) — **see §8 P12 for the 1M first-bar-anchor caveat under `extended=true`**.

**Flow B — digest (`get_stock_bars`, 1Day then 1Min).**
1. `_detect_symbol` calls `get_stock_bars(symbol, timeframe="1Day", start=now-10d, end=now, limit=10)`.
2. Seam → `_fmp_bars(symbol,"1Day", …, extended=False)` → `historical_eod` → `project_bars(intraday=False)` → daily `timestamp` = ET-midnight UTC (P6/D1).
3. `_latest_completed_daily_bar` filters `_bar_session_date(bar) < today_et` (excludes today's partial bar, P27) → `prev_bar`; `prev_close` via `_bar_close` (P1 keys present).
4. `window_start = _regular_close_utc(_bar_session_date(prev_bar))` (16:00 ET → UTC). Because the daily `timestamp` is ET-midnight UTC, `_bar_session_date` resolves to the correct ET day (D1), so `window_start` is identical to today's Alpaca-derived value.
5. `get_stock_bars(symbol, timeframe="1Min", start=window_start, end=now, limit=10000)` → seam → `_fmp_bars(..., extended=True)` (P11) → `historical_chart("1min", extended=true)` → ET→UTC timestamps (P5). (FMP returns the whole prior session from 04:00 ET; only the max-timestamp bar is consumed — P23/M2.)
6. `_latest_bar_with_close` takes max-by-timestamp (parses `Z`-ISO correctly because of P5) → `change_pct`, `has_premarket_activity=True`.
   **Parity hinges on P5 (localization) + P6 (daily anchor) + P11 (`extended=true`).**

**Flow C — earnings (`_fetch_earnings`, 1Day/730d).**
1. Inside `gather(return_exceptions=True)`: seam → `_fmp_bars(symbol,"1Day",730)` → `historical_eod` → daily projection (split-adjusted P9; ET-midnight UTC `timestamp` P6).
2. `compute_earnings_reactions` matches `report_date` against `_parse_iso_date(bar["timestamp"])[:10]` — `…T05:00:00Z`[:10] = the correct ET session date (P6).
3. Any exception → `[]` reaction rows; `get_stock_info` never fails (P8 + existing degrade).

**Flow D — empty result (any entrypoint).**
1. FMP returns `200 []` (invalid/thin/IPO symbol, P8).
2. `historical_chart`/`historical_eod` → `return data or []` (D2 — no raise).
3. `project_bars([])` → `[]`. `get_chart` → `{"bars":[]}` → `_cache_set` still runs (P19) → REST 200. AI card still renders (initial range empty ≠ exception). Digest → `_empty_move`/`_flat_move`. Earnings → no reactions.

**Flow E — error paths.**
- Connection drop → `MarketDataUnavailableError` (P13) → REST 503; digest catches → degraded `_DetectionResult`; charts → "temporarily unavailable"; earnings → degrade.
- FMP 5xx/429 → `MarketDataUpstreamError` (P14) → REST 502; same handling.
- FMP 402 → `MarketDataError` (P16) → REST 404 "no data"; digest does **NOT** catch it → propagates per existing earnings/`gather` degrade and chart "no data" path; surfaces the coverage gap rather than masking it.

---

## 8. The Extended-Hours-on-Charts Decision

The one place where "preserve everything Alpaca does" is in genuine tension with a cleaner-product instinct. It must be ratified, not assumed — and the reviews surfaced that the blast radius is larger than the prior draft stated.

**The fact.** Today's Alpaca call sends **no** session/`extended_hours` param (`market_data.py:743-752` — exactly six params, none session-related). Alpaca's market-data v2 bars endpoint with `feed=iex` returns whatever IEX carried, which **includes pre-market (04:00 ET) and after-hours (20:00 ET) prints by default**. So today's charts already include extended-hours bars *wherever IEX had a print*. The decisive corroboration is the digest: it detects premarket moves purely from these default-path bars and is in production (`moves.py:196-215`).

**The under-stated blast radius (review correction).** It is not only sparkline density. For 1W (`30Min`) and 1M (`1Hour`), `change_for_range` computes `change_abs = price - bars[0].c` where `bars[0]` is the **oldest** bar (`_performance.py:33`), and this is the BE-authoritative change value iOS shows on the card (`RangeBars.changeAbs/changePct`, `Block.swift:181-186`). Under `extended=true`, `bars[0]` becomes the 04:00 ET premarket print instead of the 09:30 open. **Crucially, IEX premarket coverage is sparse per symbol, while FMP's consolidated `extended=true` is dense** — so even the "parity-faithful" `extended=true` can shift the displayed 1W/1M `change_pct` versus today for symbols where IEX simply had no early print. 1D is immune (uses the daily change, `_performance.py:29-30`).

**Two options.**
- **Option A — `extended=true` on charts (parity-faithful default).** Keeps the premarket leg, matching today's IEX-includes-extended behavior. Cost: denser sparkline; and the 1W/1M first-bar anchor shifts where FMP has premarket prints IEX lacked → a *displayed* change-value drift that must be measured, not assumed (DoD #6).
- **Option B — `extended=false` on charts (regular-session only).** 1W/1M `bars[0]` = 09:30 open, which for many symbols is *closer* to today's effective Alpaca behavior (sparse IEX premarket). But it drops the 1D premarket leg on gappers — an observable change to the 1D sparkline — and diverges from the digest's session model.

**Prior-plan correction.** The prior plan's open-question #3 called `extended=false` "matching today." That is **false** — verified against `market_data.py:743-752` + the digest dependency: today's IEX default *includes* extended hours, so `extended=false` is a change.

**Decision (owner, 2026-06-02): Option B — regular-session-only charts.** `get_chart` passes `extended=False`; the digest keeps `extended=True` (non-negotiable, P11). Rationale: a cleaner, less-noisy line for beginners, the range %-change stays anchored to the open, and the overnight/premarket *insight* is still delivered through the morning digest. This is a deliberate UX choice — today's IEX-premarket-on-charts was an unintended side effect of the feed, not a product feature — and it is reversible (a future opt-in "show extended hours" toggle could revisit it). **O3 is closed as a product decision.** The staging parity sweep still measures the residual regular-session close drift, but no longer gates on a chart change-value sign-off.

---

## 9. Config / DI / Dead-Code

**Add:**
- `app/config.py`: `fmp_bars_enabled: bool` (env `FMP_BARS_ENABLED`, default `false`). `fmp_api_key` already exists (`config.py:77`); the `FmpClient` is already constructed in `lifecycle.py:45-46` and `worker.py:179` — no new DI wiring; the new bar methods live on the existing client.
- `app/services/fmp.py` imports: `from decimal import Decimal` and `from zoneinfo import ZoneInfo` (and `time` from `datetime`) — currently absent (`fmp.py:1`). Without these, `project_bars`/`_resample_weekly` `NameError`.
- `app/services/market_data.py`: split `_INTRADAY_TIMEFRAMES` (`:69`) into `_INTRADAY_TTL_TIMEFRAMES` (TTL switch) and `_INTRADAY_BAR_TIMEFRAMES` (dispatch). The TTL switch keeps its current three-token set.

**Keep — forever (clock + token plumbing, P28):** `_alpaca_clock`, `_alpaca_get`, `_alpaca_headers`, `self._alpaca_client`, `self._alpaca_broker` / `access_token()`, the OAuth token cache, `self._alpaca_broker_url` (= `settings.alpaca_base_url`, `config.py:114-118`). These feed `get_market_status` + quote-TTL. `test_close_closes_both_clients` pins `_alpaca_client` shutdown.

**Keep — permanently (the revert target, owner decision 2026-06-02):** `_alpaca_bars`, the `_bars` flag wrapper, the `alpaca_data_url` ctor param, `settings.alpaca_data_base_url`, and the `fmp_bars_enabled` flag + dual-path branch. These stay indefinitely so a revert is always one env var away.

**Remove — nothing.** The Alpaca bar path is retained permanently as the fallback; there is no cleanup/deletion PR. (The clock-related `alpaca_base_url` and all `_alpaca_get`/headers/client/broker references stay regardless, as before.)

---

## 10. Test Architecture

Tests that *prove* parity, mapped to the matrix rows they defend. Backend tests under `tests/`; the iOS mirror is untouched (DoD #1).

**Unit — projection (`tests/unit/test_market_data_service.py`), the primary contract:**
- **Rewrite** `test_miss_calls_*` / `test_get_stock_bars_passes_explicit_window` → drive the FMP path: assert `apikey` present, **no bearer header**, **both `from`+`to` sent**, the exact 8-key dict (P1/P2a), `vwap`/`trade_count` synthesized (P3/P4), `volume` int from a float input (P2b — assert `int(2667385.76) == 2667385`), ascending order (P7).
- **ADD `test_intraday_timestamp_dst`** (mandatory, DoD #4 / P5): `15:55 EDT → 19:55Z` and `15:55 EST → 20:55Z`.
- **ADD `test_daily_timestamp_is_et_midnight_utc`** (mandatory, DoD #2 / P6 / D1): a winter daily date → `…T05:00:00Z`, a summer date → `…T04:00:00Z`; assert `ISO8601`-internet-datetime-parseable and `[:10]` == the FMP date and the digest `.astimezone(ET).date()` == the FMP date. Guards against any regression to date-only or `T00:00:00Z`.
- **ADD `test_chart_window_is_bounded`** (P23): 1M sends `to≈now`, `from≈now−30d`, guarding against `end=None` reintroduction.
- **ADD digest extended-hours assertion** (P11): `get_stock_bars(..., timeframe="1Min")` calls `/historical-chart/1min?...&extended=true`; `1Day` does not send `extended`.
- **ADD `test_empty_chart_returns_empty_bars`** (P8/D2): FMP `200 []` → `{"bars": []}`, no raise, `_cache_set` still called.
- **KEEP** TTL tests (`test_intraday_timeframe_uses_short_ttl` / `test_daily_timeframe_uses_long_ttl`, P19) — now also asserting empty `[]` still writes TTL — and add a regression asserting `4Hour`/`1Min` are absent from `_INTRADAY_TTL_TIMEFRAMES` (m-split).
- **Repoint** bearer/token-failure tests to `get_market_status` (the surviving Alpaca-token caller, P15/P28). **KEEP** all clock tests (`TestGetMarketStatus`, `TestQuoteTtlClockFallback`, `test_close_closes_both_clients`).
- **Earnings-reaction tests** (`test_parallel_fetch_merges_keys`, `test_unreported_quarter_excluded_from_reaction`): swap raw Alpaca bars for FMP daily shapes; assert ET-midnight-UTC `timestamp[:10]` still matches the correct session (P6).

**Unit — schema (`tests/unit/test_market_data_schemas.py`):** `TestPriceBar` (8 required fields), `TestChartResponse` (nested-bar error loc, empty bars OK) — unchanged; pass because the projection is identical (DoD #1).

**Unit — earnings (`tests/unit/test_fmp_client.py::TestComputeEarningsReactions`):** unchanged (feeds `{timestamp, close}` dicts) — backstops the date-match contract (P6).

**Unit — digest (`tests/unit/test_digest_moves.py`):** today feeds raw `t`/`c` dicts and does **not** exercise projected keys — a real gap. **ADD** a case that feeds the *projected* daily `timestamp` (ET-midnight UTC) and a projected 1Min `timestamp` (`Z`-ISO from a naive-ET source), and asserts (a) `_latest_completed_daily_bar` excludes a "today" partial daily bar (P27), (b) `window_start` equals the exact expected 16:00-ET-of-prev-session UTC value under both EST and EDT (locks D1 ↔ `_regular_close_utc`, B2), and (c) correct latest-1Min-bar selection (P5). This is the unit-level lock on the most cross-coupled seam.

**Unit — weekly:** **ADD `test_resample_weekly`** (P26): a multi-week input straddling a week boundary and the ISO week 1/53 boundary; assert ascending, valid `PriceBar`s, O=first/H=max/L=min/C=last/V=sum, and `timestamp` carries the full-ISO ET-midnight form.

**AI tools (`tests/ai/unit/test_display_stock_card_tool.py`, `test_stock_info_tool.py`):** **ADD `test_initial_range_empty_renders_card`** (P8) — empty `{"bars":[]}` → card still renders, no suppression. Existing `bars[0]`-change tests (P7) and `{t,c}` extraction tests stay green unchanged.

**Integration (`tests/integration/test_market_data_routes.py`, `test_digest_service.py`):** unchanged — service mocked / 8 keys preserved; the wire-shape and end-to-end-digest backstops.

**New fixtures (`tests/fixtures/mock_responses/`, sourced from `.context/fmp_probes/`):**
- `fmp_chart_intraday.json` — naive-ET `date`, no vwap/trade_count, mixed int/float volume (5min last bar 15:55).
- `fmp_chart_intraday_extended.json` — 04:00→19:59 ET (digest/extended assertions).
- `fmp_eod_full.json` — real `vwap`, date-only `date`, including a "today" partial row for the P27 digest test.
- `fmp_chart_empty.json` — `[]`.
The existing `market_data_chart.json` (projected golden, all 8 fields, full-ISO `Z`) stays as the REST integration golden — its daily-style rows already use `…T00:00:00Z`-shaped strings; update them to the ET-midnight form so the golden reflects D1.

**Staging parity verification (runs in PR 2, gates flag flip):**
- DST date parity (March + November) for intraday localization.
- Curated-mover digest run + zero-false-positive flat basket (DoD #5).
- Daily-close diff scan, flag > 0.5% (DoD #6).
- **1W/1M `change_pct` Alpaca-vs-FMP basket** under the chosen `extended` value (DoD #6 / §8 / O3).

---

## 11. Risks & Open Decisions (ranked, parity-focused)

| Rank | Item | Type | Verdict / action |
|---|---|---|---|
| **O1** | **Intraday split-adjustment (P10)** | ✅ CLOSED (2026-06-01) | Probed NVDA 1hour across the 2024-06-10 10:1 split: all bars ~$117–$127 incl. pre-split (back-adjusted) → FMP intraday IS split-adjusted, matches Alpaca. No longer blocks PR 3. |
| **O2** | **FMP Ultimate per-minute cap unconfirmed (P25)** | OPEN | **Blocks PR 3.** Confirm the cap from the FMP dashboard. Run a full-scale staging digest; if it 429s, add `Retry-After` backoff + concurrency bound (429→`MarketDataUpstreamError` already caught). `RunScopedStockBarsProvider` already dedups per run. |
| **O3** | **Charts `extended=true` shifts displayed 1W/1M `change_pct` (P12)** | DECISION + verify | **PR-2 owner-sign-off gate.** Default `extended=true` (§8). Run the 1W/1M change-value basket (DoD #6); if drift is material, owner picks A (accept more-complete-data drift) vs B (`extended=false` regular-session charts). Not a silent default. |
| **O4** | **Charts gain today's partial daily bar (P27)** | OPEN evidence gap | **Should close before PR 3.** Probe whether Alpaca daily returns a partial current-day bar intra-session. If it doesn't and FMP does, either bound chart daily `to = yesterday(ET)` or accept+document the trailing point. Digest + earnings immune. |
| **R-tz** | Intraday timestamp not localized → silent 4–5h shift (P5) | Designed, must test | `_intraday_timestamp`; mandatory DST test (EDT + EST); staging March/November parity check. |
| **R-daily-ts** | Daily emitted date-only or `T00:00:00Z` → live iOS scrub-label break / digest day-rollback (P6/D1) | Designed, must test | Emit ET-midnight UTC; `test_daily_timestamp_is_et_midnight_utc` + the digest `window_start` test lock it under both DST regimes. |
| **R-ext-digest** | Digest 1Min missing `extended=true` → all moves flat (P11) | Designed | `extended` true for the digest 1Min leg always; curated-mover gate + liveness floor (DoD #5). |
| **R-empty** | Empty `[]` raises or skips cache (P8/D2) | Designed | `return data or []`; empty-render + empty-caches tests; overrules `FINDINGS.md:46`. |
| **R-fields** | vwap/trade_count dropped or volume float crashes (P2b/P3/P4) | Designed | Synthesize both; `int_or_zero(volume)`; projection test pins the 8-key dict + the float→int truncation. |
| **R-sort** | Newest-first not reversed (P7) | Designed | `reversed(rows)`; `bars[0]`-as-oldest and sparkline-order tests. |
| **R-402** | Digest swallows `MarketDataError` and hides a 402 coverage gap (P16) | Designed | No blanket `except MarketDataError`; empty already degrades via `_empty_move`. |
| **R-window** | FMP date-granular `from` drops the digest 16:00-ET lower bound (P23/M2) | Designed | Safe for the current consumer (max-timestamp bar only); digest test pins it so a future "first overnight bar" reader can't silently regress. |
| **R-week** | 5Y ISO-week boundary divergence (P26) | Designed | ISO `(year,week)` keying; `test_resample_weekly`. No AI consumer; low stakes. |
| **R-ttl-drift** | Overloaded `_INTRADAY_TIMEFRAMES` couples TTL to dispatch (P19/m-split) | Designed | Two frozensets; TTL test asserts `4Hour`/`1Min` are not TTL-intraday. |
| **R-clock** | Clock plumbing accidentally removed (P28) | Designed | Explicit keep-list (§9); clock tests stay green; no cleanup PR — the Alpaca path is kept, clock refs stay regardless. |
| **R-limit** | `limit` silently a no-op under FMP (P22) | Inherent | Keep signature for protocol/cache-key parity; document the no-op. Was effectively a no-op under Alpaca too. |
| **R-price** | Consolidated-vs-IEX price disagreement near digest thresholds | Accepted | The *intended* data change. Both digest legs become FMP → internally consistent; parity flags daily-close diffs > 0.5%. |

**Rollout.** PR 1 = additive `FmpClient` bar methods + `project_bars`/`_intraday_timestamp`/`_daily_timestamp`/`_resample_weekly` + the `Decimal`/`ZoneInfo` imports + the `_INTRADAY_*` split + tests/fixtures (no wiring; includes the O1 NVDA-straddle and O4 Alpaca-partial-bar probes). **The daily-timestamp form (D1) is decided in PR 1 because `project_bars` ships here.** PR 2 = `_fmp_bars` dispatcher + call-site rewrites + flag (`FMP_BARS_ENABLED=false`) + rewritten tests + empty-render + digest `window_start` test; staging parity verification (DoD #4/#5/#6) runs here; **O3 owner sign-off gates the flag flip.** PR 3 = enable `FMP_BARS_ENABLED` per environment (Railway env var on `web` + `worker`) — **no code deletion; Alpaca kept as the permanent fallback** — **gated on O2 closed and O4 resolved (O1 ✅ closed by probe; O3 ✅ closed: regular-session charts).** Run `be-auditor` per PR.

---

## 12. Adversarial findings dispositions (audit trail)

Folded in (all three reviews converged on the first two):
- **PB1 / B1 (daily date-only is a LIVE iOS-card break), accepted** → D1 / P6 / DoD #2 changed to ET-midnight UTC; verified via `SingleStockCard.swift:44-45`, `ISO8601Coder.swift:11-12`, `_performance.py:13`.
- **PB2 / B2 (wrong Alpaca anchor; digest day-rollback under `T00:00:00Z`), accepted** → resolved by the same ET-midnight-UTC form; verified the three encodings against `_parse_bar_timestamp`/`_bar_session_date` across EST/EDT. The repo fixtures (`test_market_data_service.py:367-377`, `T05:00:00Z`) are the empirical anchor, not the prior draft's `T00:00:00Z`.
- **B1/M2 extended-hours change-value blast radius, accepted** → §8 rewritten; P12 risk expanded to "displayed `change_pct`"; DoD #6 adds the 1W/1M change basket; O3 made a PR-2 sign-off gate.
- **M1 / P27 partial daily bar on charts, accepted** → new P27 row + O4 probe gate; digest/earnings shown immune.
- **M3 / P10 verdict overstated, accepted** → P10 re-tagged UNPROVEN (was EQUIVALENT); already a PR-3 gate (O1).
- **P2 intraday volume verdict, accepted** → split into P2a (IDENTICAL) / P2b (EQUIVALENT, truncation named).
- **P3 intraday vwap rationale, accepted** → re-described as a real-value→"0" drop justified by no-consumer, not a missing-key match.
- **m-split (`_INTRADAY_TIMEFRAMES` overloaded), accepted** → two frozensets (§6.3, §9).
- **m1 (`Decimal`/`ZoneInfo` not imported in `fmp.py`), accepted** → added to §6.2/§9 import list (verified absent).
- **m-cache (don't refactor `get_chart:234-240`), accepted** → §6.6 implementation note.
- **iOS citation rot, accepted** → paths corrected to `Sevino/Sevino/Utils/ISO8601Coder.swift`, `Models/MarketData/MarketDataModels.swift:128-141` (REST `PriceBar`), `Models/Chat/Block.swift:163-168` (AI `Bar`).

Dropped (with reason):
- *"Use `T00:00:00Z` to fix the iOS break"* — **rejected:** verified it rolls the digest `_bar_session_date` back one day for every date; ET-midnight UTC is the only safe form.
- *"`extended=false` matches today"* (prior plan OQ#3) — **rejected:** today's IEX default *includes* extended hours (`market_data.py:743-752` + digest dependency); `extended=false` is a change, not a match.
- *"New bar methods should raise on empty like `quote()`"* (`FINDINGS.md:46`) — **rejected (D2):** every bar consumer depends on empty→`[]`; raising would break `get_chart` 200-on-empty, the card render, and the digest/earnings degrade paths.
- *"`limit` truncation parity"* — **dropped as non-issue:** `limit=10000` never bound under Alpaca at current window sizes; the FMP no-op is behaviorally identical.
- *"REST date-only iOS decode is a live break"* — **partially dropped:** no live SwiftUI view calls `getChart`, so the REST path is genuinely latent; the *live* break is the AI `Bar` path (PB1), which D1 fixes regardless.
