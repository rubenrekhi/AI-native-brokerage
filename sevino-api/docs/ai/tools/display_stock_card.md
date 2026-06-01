# `display_stock_card`

Registered agent tool that renders the **inline visual stock card** for one US-equity ticker — logo, current price, daily change, an interactive chart (every range pre-loaded), and an optional valuation/technical stats grid. The card goes to the **user** as a `StockCardBlock`; the model only gets a lean acknowledgement. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow. Its sibling [`get_stock_info`](get_stock_info.md) reads the same data for the model's own reasoning; the two are **independent** — calling one does not imply the other.

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/display_stock_card.py` · `DisplayStockCard` |
| Reads | quote/profile/ratios + one chart per range (`MarketDataService.get_stock_info` + `get_chart`), all fetched concurrently |
| Freshness | same caches as [`get_stock_info`](get_stock_info.md) — quote ~15s, fundamentals ~12h, charts 60s/1h |
| Status pill | none of its own (see [below](#wire--no-pill-of-its-own)) |
| Output target | the **user** — a `StockCardBlock` (`ui_block`) |

The model renders the card when it would help the user to *see* a stock — a chart of how it moved, or its price plus key stats — rather than only read about it. The card replaces **data dumps** in prose (lists of price/volume/P-E/52w fields), not conversational answers: the model keeps answering the question in plain text and calls this tool alongside to add the visual. It is used **at most once per turn per symbol**, and skipped for passing mentions, tickers being reasoned about but not recommended, or one-sentence answers that need no chart. The system prompt (`app/ai/prompts/sevino_v1.md` §"Showing stock data visually") owns this higher-level behaviour.

It reuses the same `MarketDataService` and the shared change-for-range math (`app/ai/tools/_performance.py`) as `get_stock_info`, so the card's numbers can't drift from the model's prose.

---

## Input — `DisplayStockCardInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `symbol` | `str` (1–10 chars) | — (required) | US-equity ticker. Case-insensitive — the tool uppercases it. One symbol per call. |
| `range` | `1D \| 1W \| 1M \| 3M \| 6M \| 1Y` | `1M` | Initial timeframe the chart lands on. The card pre-loads **every** range so the user can slide to others; this only sets the starting view. |
| `expanded` | `bool` | `false` | When `true`, include the stats grid (open/high/low, 52-week range, volume, market cap, P/E, EPS, dividend yield, …) below the chart. For valuation/fundamentals answers; skip for casual lookups where the compact card is cleaner. |

---

## Output

### `model_payload` — a lean acknowledgement

On success: `{"displayed": true, "symbol", "range", "expanded"}`. **The data is not in the payload** — it rides in `ui_block`. This keeps the model's follow-up context small; the model already read the numbers via `get_stock_info` (or the prose it's writing). On failure: `{"error", "symbol"}` and **no `ui_block`** (no card is shown).

`internal_trace` (audit only) carries `{"quote", "ranges_loaded"}`.

### `ui_block` — `StockCardBlock`

`symbol`, `company_name` (profile name, falling back to the symbol), `logo_url`, `price`, `change_abs`, `change_pct` (the change **for the initial range**), `color_state` (`positive`/`negative`/`neutral`, from the change sign), `bars` (the initial range's series), `bars_by_range` (every range that loaded — each `{range, bars, change_abs, change_pct}`), `range`, `range_options`, and `stats`.

`stats` is a `StockStats` grid when `expanded=true`, else `null`: `open`, `day_high`, `day_low`, `previous_close`, `year_high`, `year_low`, `volume`, `avg_volume`, `market_cap`, `pe_ratio`, `eps`, `beta`, `dividend_yield`, `exchange`. **Zero / empty FMP values are dropped to `null`** so iOS skips the row instead of rendering "$0.00".

---

## Data semantics

The card uses **floats**, not the `MoneyStr` string contract — it is a display block, not a portfolio response. `change_pct` is a **fraction of 1** (`0.0065` = 0.65%); FMP's raw percent is converted inside the tool so iOS stays FMP-agnostic. `1D` change is vs. yesterday's close (FMP's daily change); longer ranges diff the first bar to the current price (the shared `_performance` helper, identical to `get_stock_info`'s `performance`).

---

## Failure modes

All failures return an `{"error", "symbol"}` `model_payload` and no card; the tool never raises for these expected conditions.

| Cause | Result |
|---|---|
| Info lookup failed — unknown/invalid ticker | `{"error": "No data found for ticker {SYMBOL}.", ...}`, no card |
| The **initial** range's chart is missing or failed | Card suppressed — the chosen view is load-bearing — same "No data found" error |
| **Every** range's chart failed | Same error payload, no card |
| Upstream down / unavailable (`MarketDataUnavailableError`, `MarketDataUpstreamError`) | `{"error": "Market data provider is temporarily unavailable.", ...}` |
| `ctx.http_clients.market_data` is `None` | `{"error": "Market data service is not configured in this environment.", ...}` |

A **non-initial** range failing is **non-fatal** — that range is dropped from `bars_by_range` and logged; iOS falls back to the top-level `bars` for it. Only the initial range must succeed.

---

## Wire — no pill of its own

Unlike `get_stock_info`, this tool emits **no status pill and no interim event**. It returns the `StockCardBlock` as `ui_block`, and the dispatch layer sends `BlockStart` + `BlockEnd` around it (the `RecordingEmitter` saw no inline `BlockStart`, so it doesn't dedup — see [`../ai-harness.md`](../ai-harness.md) §6).

`StockCardBlock` (with `Bar`, `RangeBars`, `StockStats`) is an **existing** member of the `Block` union (`app/ai/blocks.py`), hand-mirrored in iOS `Block.swift`. This tool adds no new variant, but adding/removing a field on `StockCardBlock` requires a matching iOS change — there is no codegen and no CI check, and drift breaks the iOS decoder at runtime (cf. [`../ai-harness.md`](../ai-harness.md) §9 and `CLAUDE.md`).

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Clients** — needs `ToolHttpClients.market_data`; `None` → the "not configured" error above.
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"Showing stock data visually (`display_stock_card`)".
- **Tests** — `tests/ai/unit/test_display_stock_card_tool.py`.
