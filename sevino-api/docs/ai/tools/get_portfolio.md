# `get_portfolio`

Registered agent tool that reads the user's **own** brokerage account: balances (equity, cash, buying power), today's change, and holdings. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow. Its sibling, [`get_portfolio_performance`](get_portfolio_performance.md), reads the account's value over a time range.

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/portfolio.py` · `GetPortfolio` |
| Reads | snapshot + holdings, via `PortfolioService.get_snapshot` + `get_holdings` (fetched concurrently) |
| Freshness | real-time — snapshot and holdings are uncached, so they never lie post-trade |
| Status pill | "Reading your portfolio" |
| Shared runtime | `app/ai/utils/portfolio_tool_runtime.py` (see [below](#shared-runtime)) |

This tool reads the account as a whole, or the user's positions in it. For a security's own price or fundamentals — the stock, not the user's stake in it — the model uses `get_stock_info` instead, and it prefers portfolio data already present in the turn's attached context over calling this tool at all. Both the tool description and the system prompt (`app/ai/prompts/sevino_v1.md` §"Reading the user's portfolio") steer it that way.

It does not re-implement the Alpaca calls — it reuses `PortfolioService` (the same service behind `GET /v1/portfolio/snapshot|holdings`) and then **aggregates server-side** so the model gets a lean payload instead of the full position list.

---

## Input — `PortfolioInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `detail` | `"overview" \| "positions"` | `"overview"` | `overview` → balances + a rollup of the largest holdings; `positions` → the full holdings list with per-position cost basis and unrealized P/L. |
| `symbols` | `list[str] \| None` | `None` | When set, returns those positions only and reports any not held — uncapped, so the model can expand all of `omitted_symbols` in one call. **Overrides `detail`.** |

---

## Output — `model_payload`

Every mode returns the **balance header**: `as_of`, `account_status`, `equity`, `cash`, `buying_power`, `invested` (total market value), `day_change_abs`, `day_change_pct`. Then, by mode:

### `detail="overview"` (default)

Adds a `holdings` rollup:

- `count` — number of open positions.
- `top` — up to 5 positions by market value, each `{symbol, name, value, weight, day_change_pct}`.
- `concentration_note` — e.g. `"Top 3 of 12 positions make up 64% of invested value."`

An all-cash account returns `count: 0`, an empty `top`, and a "entirely cash" note.

### `detail="positions"`

Adds `count` and `positions` — full per-position entries (below) for the **20 largest holdings by market value**. If the user holds more than 20, it also sets `truncated: true`, lists every remaining holding by ticker only in `omitted_symbols` (in market-value order), and adds a `more` hint telling the model it can request full detail on any of those via `symbols`.

### `symbols=[...]`

Adds `positions` (only the requested tickers, matched case-insensitively) and `not_held` (the sorted tickers the user doesn't hold). Matching runs against the **full** holdings list, not just the top 20 — so it resolves tickers from `omitted_symbols`, which is how the model expands a holding the `positions` cap left as a bare ticker.

### Per-position entry

`symbol`, `name`, `qty`, `avg_entry_price`, `current_price`, `market_value`, `cost_basis`, `unrealized_pl`, `unrealized_pl_pct`, `day_change_abs`, `day_change_pct`, `weight`.

`weight` is `market_value / total` quantized to 4 decimal places (`"0.0000"` when there is nothing invested).

`internal_trace` (audit only) carries the full snapshot + holdings dumps.

---

## Shared runtime

`get_portfolio` and `get_portfolio_performance` share account setup, error payloads, and the status-pill lifecycle in `app/ai/utils/portfolio_tool_runtime.py`.

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

Every money, quantity, and percentage value is a **string**, not a number (`MoneyStr` / `QtyStr` / `PctStr` — see `schemas/_types.py`). They are exact decimals; the model must quote them as-is and never round or do floating-point math on them. **Percentages are fractions of 1** — `"0.0117"` means 1.17%. `as_of` is the UTC time the tool fetched the data.

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Clients** — needs `ToolHttpClients.alpaca` and `.redis`; `post_turn` (`routes/conversations.py`) populates them from `request.app.state`. Both are `None` only when the app booted without a lifespan.
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"Reading the user's portfolio".
- **Tests** — `tests/ai/unit/test_portfolio_tools.py`.
