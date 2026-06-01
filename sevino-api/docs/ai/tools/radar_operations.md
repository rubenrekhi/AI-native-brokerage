# `radar_operations`

Registered agent tool that reads or mutates the user's **radar** — their personal watchlist of stocks to follow. One tool, three operations selected by `operation`: `get` lists everything on the radar, `add` lands a starred user pick, `remove` deletes a row regardless of source. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow.

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/radar_operations.py` · `RadarOperations` |
| Reads / writes | list / add / remove radar rows via `RadarService` (the same service behind the `/v1/radar` REST endpoints) |
| Freshness | live DB read — the radar table is the source of truth; `get` returns **no** price overlay |
| Status pill | "Looking at your Radar" / "Adding ${TICKER} to your radar" / "Removing ${TICKER} from your radar" |
| Session | opens its own DB session from `ctx.db_factory` |

The model calls `get` on demand ("what's on my radar?", "is NVDA on my radar?") — or skips it when the radar already arrived as attached context (the user has it open). It calls `add` / `remove` **only** when the user explicitly asks to change the radar ("add NVDA", "drop Apple"), never just because a ticker came up. The system prompt (`app/ai/prompts/sevino_v1.md` §"The radar") owns this guidance.

---

## Input — `RadarOperationsInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `operation` | `add \| remove \| get` | — (required) | Which operation to run. |
| `symbol` | `str \| None` (1–10 chars) | `None` | US-equity ticker. **Required for `add` / `remove`**, ignored for `get`. Case-insensitive — the tool uppercases it. One symbol per call. |

---

## Output — `model_payload`

Every payload echoes `operation`:

### `get`

`{"operation": "get", "count": N, "items": [...]}`. Each item: `symbol`, `company_name`, `added_by` (`"human"` when the source is user-added, else `"ai"`), and — **for AI picks only** — `reason` (the item's `context_blurb`, why Sevino surfaced it). An empty radar returns `count: 0`, `items: []`.

### `add`

`{"operation": "add", "symbol", "status": "added", "company_name", "starred": true}` — the row lands starred and user-added (persists, no expiry). If the ticker is already on the radar, the end-state the user asked for already holds, so it's a **soft success**: `{"status": "already_on_radar"}`.

### `remove`

`{"operation": "remove", "symbol", "status": "removed"}`, deleting the row whether it was user-added or AI-surfaced. If the ticker wasn't on the radar, the absence already holds: `{"status": "not_on_radar"}` (also a soft success).

### Error

`{"operation", "symbol", "status": "error", "error": "<message>"}`. The tool description tells the model to relay the message briefly and not retry the same call.

---

## Idempotency & failure modes

The tool treats the operation's **end-state** as success, so the model can phrase outcomes naturally. Soft successes (`already_on_radar`, `not_on_radar`) settle the pill to `complete`, not `failed`.

| Condition | Pill | Payload |
|---|---|---|
| `add` / `remove` with no `symbol` | **no pill** (nothing happened) | `status: "error"`, "A ticker symbol is required to add or remove a radar item." |
| Duplicate add (`RADAR_DUPLICATE_SYMBOL`) | `complete` | `status: "already_on_radar"` |
| Ticker not tradeable (`SYMBOL_NOT_TRADEABLE`) | `failed` | `status: "error"`, the rejection message (e.g. "{TICKER} is not available for trading.") |
| Any other exception | `failed` | `status: "error"`, "Your radar is temporarily unavailable." |

Two deliberate choices:

- **`ConflictError` is caught *outside* the `async with ctx.db_factory()` block** so the session rolls back first — a duplicate add raises only after a failed flush, leaving an aborted transaction that can't be committed.
- **Unexpected exceptions are captured to Sentry** before returning the graceful pill. Catching here for a clean pill means the dispatch layer's `logger.exception` never sees them, so without the explicit `capture_exception` a genuine bug would be lost as a warning-level breadcrumb. The expected business rejection (`ConflictError`) is handled separately and never escalates to Sentry.

---

## Data semantics

`get` returns **no prices** — only ticker, company name, source, and the AI reason. (The REST radar list endpoint merges a live quote overlay; the chat tool deliberately skips it via `RadarService.list_items`, which is also why it works when `market_data` is `None`.)

---

## Status pill & wire

Each call emits one `StatusBlock` — `active` at the start (via `BlockStart`), flipped to `complete` or `failed` (via `BlockData`). The label depends on the operation (see the summary table). This reuses the existing `StatusBlock` wire type, so **this tool adds no new `Block` variant and requires no iOS mirror change** (cf. [`../ai-harness.md`](../ai-harness.md) §8). Because the tool emits its own `active` pill inline, the loop's `RecordingEmitter` dedups it so the `ui_block` return isn't re-emitted ([`../ai-harness.md`](../ai-harness.md) §6). The one case with **no** pill is a missing `symbol` for `add`/`remove` — nothing happened, so nothing is shown.

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Clients** — opens its own DB session via `ctx.db_factory` and constructs `RadarService`. `ToolHttpClients.market_data` is passed through but unused by these paths, so the tool works even when it's `None`.
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"The radar (`radar_operations`)".
- **Tests** — `tests/ai/unit/test_radar_operations_tool.py`.
