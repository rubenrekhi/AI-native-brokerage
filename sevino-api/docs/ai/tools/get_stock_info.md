# `get_stock_info`

Registered agent tool that reads **live market data for one US-equity ticker** — quote, company profile, TTM fundamentals, analyst sentiment, and per-range performance — and hands the data to the model. It produces no card; the data is for the model's reasoning. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow. Its sibling [`display_stock_card`](display_stock_card.md) renders the same data as a visual card for the user; the two are independent decisions.

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/stock_info.py` · `GetStockInfo` |
| Reads | quote + fundamentals + analyst (`MarketDataService.get_stock_info`) and one chart per range (`get_chart`), all fetched concurrently |
| Freshness | quote ~15s cached (1800s when the market is closed); fundamentals ~12h; charts 60s intraday / 1h daily |
| Status pill | "Pulling data on {TICKER}" |
| Output target | the **model** (`model_payload`) — not a UI card |

The model calls this whenever it needs fresh data about a specific stock — price, valuation, fundamentals, performance, or analyst sentiment — and **always before stating any numeric value**, since training-data values may be stale. It reads the security itself; for the user's *own stake* in that security (their position, cost basis, P/L) the model uses [`get_portfolio`](get_portfolio.md) instead, and it prefers stock data already present in the turn's attached context over calling this tool. Both the tool description and the system prompt (`app/ai/prompts/sevino_v1.md` §"Reading stock data") steer it that way.

It does not re-implement the FMP/Alpaca calls — it reuses `MarketDataService` (the same service behind `GET /v1/stocks/{symbol}` and `…/chart`) and shares the change-for-range math (`app/ai/tools/_performance.py`) with `display_stock_card`, so the model's numbers can't drift from the card's.

---

## Input — `StockInfoInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `ticker` | `str` (1–10 chars) | — (required) | US-equity ticker. Case-insensitive — the tool uppercases it. One symbol per call. |

---

## Output — `model_payload`

The full dict returned by `MarketDataService.get_stock_info`, **plus** a `performance` map the tool computes. Top-level sections:

| Section | Carries |
|---|---|
| `quote` | `price`, `change`, `change_percent`, `open`, `day_high`, `day_low`, `previous_close`, `year_high`, `year_low`, `price_avg_50`, `price_avg_200`, `volume`, `avg_volume`, `market_cap`, `pe_ratio`, `eps`, `shares_outstanding`, `earnings_announcement`, `timestamp`. |
| `profile` | `name`, `sector`, `industry`, `description`, `ceo`, `website`, `employees`, `beta`, `ipo_date`, `exchange`, `logo_url`. |
| `ratios` | TTM fundamentals: `dividend_yield`, `payout_ratio`, `roe`, `roa`, `profit_margin`, `operating_margin`, `gross_margin`, `debt_to_equity`, `current_ratio`, `price_to_book`, `price_to_sales`, `ev_to_ebitda`, `free_cash_flow_yield`, `peg_ratio`. |
| `analyst` | Wall-Street targets and ratings: `target_high`, `target_low`, `target_consensus`, `target_median`, and the `strong_buy` / `buy` / `hold` / `sell` / `strong_sell` counts. |
| `financials`, `valuation`, `earnings` | Additional sections the service returns. The tool description advertises only the four above to keep the model focused, **but these ride along in the payload** and the model sees them. |
| `performance` | **Added by the tool.** Per-range `{change_abs, change_pct}` for each of `1D`, `1W`, `1M`, `3M`, `6M`, `1Y` whose chart fetched successfully. A range whose chart failed is **omitted** (the model falls back to the daily change). |

`internal_trace` (audit only) carries the full payload under `{"raw": ...}`.

---

## Data semantics

These fields are **FMP-projected** — they do **not** follow the `MoneyStr` / `QtyStr` / `PctStr` contract the portfolio tools use (`schemas/_types.py`). Most numeric values in `quote` / `ratios` / `analyst` are **strings** (so iOS and Python share `Decimal` semantics), but `volume`, `avg_volume`, `market_cap`, `shares_outstanding`, `timestamp`, and the analyst rating **counts** are integers; fields FMP omits come back as `null`.

Two percentage conventions coexist in one payload, and the model must not mix them:

- `quote.change_percent` is a **percent** — `"0.65"` means 0.65% (FMP's raw form).
- `performance[range].change_pct` is a **fraction of 1** — `0.0065` means 0.65% (the tool converts it via the shared helper, matching the card).

`1D` performance uses FMP's daily change (vs. yesterday's close); longer ranges diff the first bar to the current price.

---

## Failure modes

The tool never raises for **expected** failures — it returns an `{"error", "ticker"}` `model_payload` and flips the pill to `failed`, so the model can apologise and move on instead of ending the turn (cf. the `TOOL_ERROR` path in [`../ai-harness.md`](../ai-harness.md) §6).

| Cause | `error` message |
|---|---|
| Unknown ticker / invalid input (`MarketDataError`, `MarketDataInvalidInputError`) | `No data found for ticker {TICKER}.` |
| Upstream down / unavailable (`MarketDataUnavailableError`, `MarketDataUpstreamError`), or any unexpected exception | `Market data provider is temporarily unavailable.` |
| `ctx.http_clients.market_data` is `None` (no `FMP_API_KEY`, or the app booted without a lifespan) | `Market data service is not configured in this environment.` |

A failure of a **single chart range** is non-fatal — that range is dropped from `performance` and logged; the quote and remaining ranges still return. The tool description tells the model to apologise, ask the user to confirm the ticker, and **not** retry the same ticker repeatedly.

---

## Status pill & wire

Each call emits one `StatusBlock` — `active` at the start (via `BlockStart`), flipped to `complete` on success or `failed` on any error (via `BlockData`). This reuses the existing `StatusBlock` wire type, so **this tool adds no new `Block` variant and requires no iOS mirror change** (cf. [`../ai-harness.md`](../ai-harness.md) §8). Because the tool emits its own `active` pill inline, the loop's `RecordingEmitter` dedups it so the `ui_block` return isn't re-emitted ([`../ai-harness.md`](../ai-harness.md) §6).

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Clients** — needs `ToolHttpClients.market_data`; `None` when `FMP_API_KEY` is unset or the app booted without a lifespan (→ the "not configured" error above).
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"Reading stock data".
- **Tests** — `tests/ai/unit/test_stock_info_tool.py`.
