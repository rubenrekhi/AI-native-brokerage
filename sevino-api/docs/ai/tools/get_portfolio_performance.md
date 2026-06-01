# `get_portfolio_performance`

Registered agent tool that reads how the user's **own** brokerage account value has changed over a time range — start/end value, gain, high/low, and the shape of the curve. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow. Its sibling, [`get_portfolio`](get_portfolio.md), reads current balances and holdings.

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/portfolio_performance.py` · `GetPortfolioPerformance` |
| Reads | the portfolio value series, via `PortfolioService.get_history` |
| Freshness | up to ~60s stale — history is Redis-cached (60s TTL) |
| Status pill | "Reading your performance" |
| Shared runtime | `app/ai/utils/portfolio_tool_runtime.py` (see [below](#shared-runtime)) |

Use this for "how has my portfolio done this month", "am I up over the past year", or any return/performance question about the account **as a whole**. For a single stock's price history — the security, not the user's account — the model uses `get_stock_info` instead, and it prefers performance data already present in the turn's attached context over calling this tool. Both the tool description and the system prompt (`app/ai/prompts/sevino_v1.md` §"Reading the user's portfolio") steer it that way.

It does not re-implement the Alpaca call — it reuses `PortfolioService.get_history` (the same path behind `GET /v1/portfolio/history`, including its 60s cache — see `cache.py` and [`../../alpaca-integration.md`](../../alpaca-integration.md) §"Portfolio Read Endpoints") and then **reduces the series server-side** so the model gets gain stats and a short trend instead of the raw curve.

---

## Input — `PortfolioPerformanceInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `range` | `1D \| 1W \| 1M \| 3M \| 6M \| YTD \| 1Y \| ALL` | `1M` | Window for the value series. Maps to `PortfolioRange`, which the service translates into Alpaca period/timeframe params. |

---

## Output — `model_payload`

`as_of`, `range`, `timeframe`, `base_value`, `end_value`, `gain_abs`, `gain_pct`, `n_points`, and:

- `high` / `low` — `{t, v}` of the max / min value point over the range.
- `trend` — the value series **downsampled to at most 16 evenly-spaced points** (`{t, v}` each), so the model can describe the shape of the curve without ingesting the raw series. A series already at or below 16 points is returned whole; an empty series yields `trend: []` and no `high`/`low`.

`internal_trace` (audit only) carries the full history dump.

---

## Shared runtime

`get_portfolio_performance` and `get_portfolio` share account setup, error payloads, and the status-pill lifecycle in `app/ai/utils/portfolio_tool_runtime.py`.

**Account setup.** `open_service(ctx, db)` loads the user's brokerage account and builds a `PortfolioService`. If there is no account or its status isn't `ACTIVE`, it raises `AccountUnavailable` to short-circuit to an error payload.

**Failures never end the turn.** A custom tool that raises sets the iteration's terminal error code (`TOOL_ERROR` — see [`../ai-harness.md`](../ai-harness.md) §6). This tool deliberately avoids that for **expected** conditions: it catches them and returns an `{"error", "code"}` `model_payload` so the model can explain the situation and move on. Only unexpected bugs propagate.

| `code` | Cause |
|---|---|
| `ACCOUNT_NOT_ACTIVE` | No brokerage account, or status ≠ `ACTIVE`. Includes `account_status`. |
| `BROKERAGE_UNAVAILABLE` | The Alpaca call failed or the broker is down (`AlpacaBrokerError` / `AlpacaBrokerUnavailableError`). |
| `PORTFOLIO_UNAVAILABLE` | `ctx.http_clients.alpaca` or `.redis` is `None` (app booted without a lifespan, e.g. some tests). |

The tool description tells the model to explain these and **not** retry repeatedly.

**Status pill.** Each call emits one `StatusBlock` — `active` at the start, flipped to `complete` on success or `failed` on any error. This reuses the existing `StatusBlock` wire type, so **this tool adds no new `Block` variant and requires no iOS mirror change** (cf. [`../ai-harness.md`](../ai-harness.md) §8).

---

## Data semantics

Every money and percentage value is a **string**, not a number (`MoneyStr` / `PctStr` — see `schemas/_types.py`). They are exact decimals; the model must quote them as-is and never round or do floating-point math on them. **`gain_pct` is a fraction of 1** — `"0.5360"` means 53.60%. `as_of` is the UTC time the tool fetched the data; the underlying history can be up to ~60s stale.

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Clients** — needs `ToolHttpClients.alpaca` and `.redis`; `post_turn` (`routes/conversations.py`) populates them from `request.app.state`. Both are `None` only when the app booted without a lifespan.
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"Reading the user's portfolio".
- **Tests** — `tests/ai/unit/test_portfolio_tools.py`.
