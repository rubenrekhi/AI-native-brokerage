# AI Agent Harness

This document describes the `app/ai/` module end to end: the agent loop that turns one user message into a streamed, persisted, audited assistant turn. The reader is assumed to know the FastAPI backend broadly but not the internals here.

Everything below is grounded in the code as it stands. File paths are relative to `sevino-api/`.

---

## 1. Overview

The harness runs **one agent turn**: a user sends a message, the loop calls Anthropic (possibly several times for tool use), streams the response to iOS over SSE, and persists a full audit trail. The single public entry point is `run_agent_turn` in `app/ai/runtime/loop.py`; the HTTP entry point is `POST /v1/conversations/{id}/turns` in `app/routes/conversations.py`.

Major moving parts:

- **Loop orchestrator** (`runtime/loop.py`) — owns the turn-level try/finally, the iterate-on-`pause_turn`/`tool_use` while-loop, cap checks, and terminal finalization.
- **Flow** (`runtime/flow/`) — one iteration's body (`iteration.py`), stream consumption (`stream_consumer.py`), and turn setup/teardown (`turn_lifecycle.py`).
- **Dispatch** (`runtime/dispatch/`) — custom registered-tool execution (`custom.py`) and Anthropic-hosted server-tool tracking (`server.py`).
- **Tools** (`tools/`) — the `Tool` ABC, `ToolRegistry`, and five concrete tools (`get_stock_info`, `display_stock_card`, `radar_operations`, `get_portfolio`, `get_portfolio_performance`). Each portfolio read tool has a dedicated reference: [`tools/get_portfolio.md`](tools/get_portfolio.md) and [`tools/get_portfolio_performance.md`](tools/get_portfolio_performance.md).
- **Transport** (`transport/`) — SSE event types (`events.py`), the bounded-queue emitter (`emitter.py`), and Redis idempotency (`idempotency.py`).
- **Blocks** (`blocks.py`) — the UI block schemas streamed and persisted; hand-mirrored by iOS.
- **Prompts / models / client / observability** — system-prompt loading, model identifiers, the Anthropic client, and the Langfuse wrapper.

Anthropic errors and cap breaches never raise out of the loop — they are persisted with `terminal_state='error'` (or a specific cap state) and surfaced as an SSE `error` frame. Only `CancelledError` propagates (after partial state is flushed).

---

## 2. Directory map

```
app/ai/
├── __init__.py                     # empty package marker
├── anthropic_client.py             # create AsyncAnthropic; get_anthropic(request) dependency
├── blocks.py                       # UI Block schemas (text/status/stock_card/thinking); iOS mirror
├── models.py                       # MODELS (MAIN/SMOKE) + get_default_model_config()
├── observability/
│   ├── __init__.py                 # empty
│   └── langfuse.py                 # real Langfuse or _NoopLangfuse stub; get_langfuse(request)
├── prompts/
│   ├── __init__.py                 # SystemPrompt loader, hashing, server-tools composition
│   ├── sevino_v1.md                # base system prompt
│   └── sevino_v1_server_tools.md   # addendum appended when server tools are enabled
├── runtime/
│   ├── __init__.py                 # empty
│   ├── loop.py                     # run_agent_turn — the orchestrator
│   ├── types.py                    # LoopState, ModelConfig, ServerToolsConfig, AgentTurnResult, ToolRegistry Protocol
│   ├── caps.py                     # HardCaps, CapBreach, check_caps()
│   ├── cost.py                     # per-invocation cost in microUSD; _PRICING table
│   ├── db.py                       # session-per-write factory (DbSessionFactory)
│   ├── errors.py                   # ErrorCode enum + to_error_code(exc)
│   ├── anthropic_io.py             # scrub_blocks, to_anthropic_content, estimate_thinking_tokens
│   ├── dispatch/
│   │   ├── __init__.py             # empty
│   │   ├── custom.py               # dispatch_tool_uses — registered tools (tool_use stop reason)
│   │   └── server.py               # ServerToolTracker — hosted web_search/web_fetch/code_execution
│   └── flow/
│       ├── __init__.py             # empty
│       ├── iteration.py            # run_one_iteration — build → stream → persist → route by stop_reason
│       ├── stream_consumer.py      # StreamConsumer — Anthropic stream → SSE block events
│       └── turn_lifecycle.py       # initialize_turn, TurnTotals, finalize_turn_row, emit_terminal_frame
├── tools/
│   ├── __init__.py                 # build_default_registry() + DEFAULT_REGISTRY
│   ├── base.py                     # Tool ABC, ToolResult, ToolContext, ToolRegistry, ToolHttpClients
│   ├── _performance.py             # shared change-for-range helper (PERFORMANCE_RANGES)
│   ├── stock_info.py               # GetStockInfo — read data for the model (pill, no card)
│   ├── display_stock_card.py       # DisplayStockCard — render the visual card
│   ├── radar_operations.py         # RadarOperations — get/add/remove on the user's radar (pill)
│   ├── portfolio.py                # GetPortfolio — balances + holdings (pill); see tools/get_portfolio.md
│   └── portfolio_performance.py    # GetPortfolioPerformance — value over a range (pill); see tools/get_portfolio_performance.md
├── transport/
│   ├── __init__.py                 # empty
│   ├── events.py                   # SSE Event union + serialize()/parse_wire_frame()
│   ├── emitter.py                  # SSEEmitter — bounded asyncio.Queue
│   └── idempotency.py              # Redis claim/complete/failed for the turn endpoint
└── utils/
    ├── __init__.py                 # package marker
    ├── time_context.py             # build_time_context — live time + market status per turn
    └── portfolio_tool_runtime.py   # shared account setup / errors / pill lifecycle (portfolio tools)
```

Persistence and wiring live outside `ai/` but are integral:

- `app/routes/conversations.py` — the HTTP endpoint, idempotency, replay, SSE driver task.
- `app/repositories/conversation.py` — `ConversationRepository`, all DB reads/writes for the audit trail.
- `app/models/{conversation,message,agent_turn,model_invocation,tool_execution}.py` — the schema.
- `app/lifecycle.py` — builds the Anthropic client, Langfuse client, `db_factory`, and `MarketDataService` onto `app.state`.

---

## 3. The request lifecycle

A single user message, traced through the exact functions it hits.

### Sequence

1. **`POST /v1/conversations/{id}/turns`** → `post_turn` (`routes/conversations.py:307`). Auth (`get_current_user`), rate limit (`@limiter.limit("30/minute")`), and body validation (`ChatTurnRequest`) run first; failures here return normal JSON errors.
2. **`ConversationRepository.ensure_owned_conversation`** — idempotent insert; creates the conversation on first turn, or 404s on ownership mismatch.
3. **`claim_idempotency`** (`transport/idempotency.py`) against Redis key `ai:idem:{user_id}:{idempotency_key}`:
   - `in_flight` → raise `ConflictError` (HTTP 409) before any stream opens.
   - `complete` → `_replay_turn` re-emits the persisted assistant message as SSE; **Anthropic is not called**.
   - `claimed` → first mover, continue.
4. **`SSEEmitter()`** is created. `post_turn` returns `EventSourceResponse(_stream())`. `_stream` spawns `_drive_turn` as a detached `asyncio.Task` and then yields events out of `emitter.iter_events()`.
5. **`_drive_turn`** builds `ServerToolsConfig` from `settings` and calls **`run_agent_turn`** (`runtime/loop.py:76`) with the emitter, `DEFAULT_REGISTRY`, `ToolHttpClients(market_data=...)`, the system prompt, model config, hard caps, and Langfuse.
6. **`run_agent_turn`** validates caps (`max_output_tokens > thinking_budget_tokens`, else `ValueError`), then **`initialize_turn`** (`flow/turn_lifecycle.py`): persists the user message (+ optional `context` block), loads history into `messages`, appends the request-only time-context block to the current user message, marks the end of prior-turn history as a cache breakpoint, and opens the `agent_turns` row. Returns `(turn_id, messages)`.
7. The loop **emits `TurnStarted`**, marks the system prompt as a (single) cache breakpoint — the live clock rides the user message instead (step 6), not a second system block — opens a Langfuse `agent` span, and enters `while True`.
8. Each iteration: `disconnect_check` (None in prod) → `check_caps` → **`run_one_iteration`** (`flow/iteration.py:195`):
   1. **`build_iteration_request`** — assembles `messages.stream` kwargs: model, system, messages, `max_tokens`, `thinking`, and a combined `tools` array (server-tool specs + registry specs, last entry `cache_control`-marked).
   2. **`StreamConsumer.consume`** (`flow/stream_consumer.py`) — opens `anthropic_client.messages.stream`, forwards chunks to SSE as `BlockStart` / `TextDelta` / `BlockData` / `BlockEnd`, and returns the final `Message`. **This is where the LLM is called.**
   3. **`scrub_blocks`** strips SDK-only fields from the response; **`cost_usd_micros`** computes cost.
   4. **`ConversationRepository.record_model_invocation`** writes one `model_invocations` row (fresh session).
   5. If server tools enabled: **`ServerToolTracker.record_executions`** pairs uses with results into `tool_executions` rows.
   6. `state.iterations += 1`, totals accumulate, the assistant `response_content` is appended to `messages` (thinking blocks included with signatures), text/server-tool-status blocks are appended to `assistant_blocks`.
   7. **`_decide_after_response`** routes on `stop_reason`:
      - `end_turn` → break, `terminal_state="end_turn"`.
      - `max_tokens` → break, `OUTPUT_TOKEN_LIMIT`.
      - `tool_use` → **`dispatch_tool_uses`** (`dispatch/custom.py`) runs every `tool_use` block in parallel; appends a `user` message of `tool_result` blocks; **continue**.
      - `pause_turn` → continue verbatim (server tool mid-flight).
      - else (refusal/stop_sequence) → break, recorded verbatim.
9. On normal break: if server tools enabled, **`flush_orphans`** closes any unmatched server-tool pills. `completed_normally = True`.
10. **`finally`** (always): `finalize_turn_row` runs under `asyncio.shield` — appends the assistant message (`assistant_blocks`) and calls `complete_agent_turn`. Then, only on `completed_normally`, **`emit_terminal_frame`** sends `TurnCompleted` (or `Error`).
11. Back in **`_drive_turn`'s finally**: `mark_complete` (only if `end_turn` with persisted blocks) or `mark_failed` on the idempotency slot (shielded), then `emitter.close()` pushes the `None` sentinel.
12. **`_stream`** sees the sentinel and ends; `EventSourceResponse` closes the HTTP stream. If `_stream` is cancelled first (client disconnect), its finally cancels the driver task.

### Diagram

```mermaid
sequenceDiagram
    participant iOS
    participant Route as post_turn (conversations.py)
    participant Redis as Idempotency (Redis)
    participant Emit as SSEEmitter
    participant Loop as run_agent_turn
    participant Iter as run_one_iteration
    participant SC as StreamConsumer
    participant Anthropic
    participant Disp as dispatch_tool_uses
    participant DB as ConversationRepository

    iOS->>Route: POST /conversations/{id}/turns
    Route->>DB: ensure_owned_conversation
    Route->>Redis: claim_idempotency
    alt in_flight
        Route-->>iOS: 409 ConflictError
    else complete
        Route->>DB: load_assistant_message_for_turn
        Route-->>iOS: replay SSE (no Anthropic)
    else claimed
        Route->>Emit: new SSEEmitter
        Route-->>iOS: EventSourceResponse(_stream)
        Note over Route: spawn _drive_turn task
        Route->>Loop: run_agent_turn(...)
        Loop->>DB: initialize_turn (user msg, history, agent_turn row)
        Loop->>Emit: TurnStarted
        loop until break
            Loop->>Loop: check_caps
            Loop->>Iter: run_one_iteration
            Iter->>SC: consume(create_kwargs)
            SC->>Anthropic: messages.stream
            Anthropic-->>SC: chunks
            SC->>Emit: BlockStart / TextDelta / BlockData / BlockEnd
            Iter->>DB: record_model_invocation
            alt stop_reason == tool_use
                Iter->>Disp: dispatch_tool_uses (parallel)
                Disp->>Emit: BlockStart / BlockEnd (tool UI)
                Disp->>DB: record_tool_execution
                Note over Iter: append tool_result user msg, continue
            else end_turn / max_tokens / other
                Note over Iter: break
            end
        end
        Loop->>DB: finalize_turn_row (shielded)
        Loop->>Emit: TurnCompleted / Error
        Route->>Redis: mark_complete / mark_failed
        Route->>Emit: close() (sentinel)
        Emit-->>iOS: SSE frames drain, stream ends
    end
```

---

## 4. Component reference

### Top-level (`app/ai/`)

| File · symbol | Purpose | In / Out · side effects |
|---|---|---|
| `anthropic_client.py` · `create_anthropic_client()` | Build `AsyncAnthropic` from `settings.anthropic_api_key`. | Called in `lifecycle.py`; stored on `app.state.anthropic`. |
| `anthropic_client.py` · `get_anthropic(request)` | FastAPI dependency returning `app.state.anthropic`. | Used by `post_turn`. |
| `models.py` · `MODELS` | Frozen `_Models(MAIN, SMOKE)`. `MAIN = settings.anthropic_model_main` (env `ANTHROPIC_MODEL_MAIN`, default `claude-sonnet-4-6`); `SMOKE = claude-haiku-4-5-20251001`. | — |
| `models.py` · `get_default_model_config()` | Returns `ModelConfig(model_id=MODELS.MAIN)`. | Dependency for `post_turn`. |
| `blocks.py` · `TextBlock`, `StatusBlock`, `ThinkingBlock`, `StockCardBlock` (+ `Bar`, `RangeBars`, `StockStats`) | Pydantic models for UI blocks streamed via SSE and persisted to `messages.content_blocks`. `Block` is the discriminated union; `BlockAdapter`/`BlockListAdapter` are `TypeAdapter`s. | **Hand-mirrored by iOS** (`Block.swift`). `ThinkingBlock` is streamed but never persisted. Note: the `context` block type used for user-attached data is **not** part of this union — it is constructed inline in `initialize_turn` and only handled by `to_anthropic_content`. |

### Runtime core (`app/ai/runtime/`)

| File · symbol | Purpose | Notes |
|---|---|---|
| `loop.py` · `run_agent_turn(**kwargs)` | The orchestrator. One outer try/except/finally guarantees the `agent_turns` row finalizes even on cancellation. Iterates while `stop_reason` is `tool_use`/`pause_turn`. | No FastAPI imports — collaborators are injected, so it can run in sub-agents/tests. Returns `AgentTurnResult`. `_BREACH_TO_ERROR_CODE` maps cap breaches to error codes (`TIMEOUT`→`INTERNAL_ERROR`). |
| `types.py` · `LoopState` | Mutable per-turn counters: `iterations`, `tool_calls`, `output_tokens`, `started_at_monotonic`. | Passed by reference into `run_one_iteration`. |
| `types.py` · `ModelConfig` | Frozen `model_id` holder. | — |
| `types.py` · `ServerToolsConfig` | Flags + max-uses for hosted tools; `any_enabled` property. `DISABLED_SERVER_TOOLS` is the default-off singleton. | Built per request in `post_turn`. |
| `types.py` · `AgentTurnResult` | Return shape: `turn_id`, `terminal_state`, `assistant_message_blocks`, `total_cost_usd_micros`, `iterations_count`. | Consumed by `_drive_turn` to decide replayability. |
| `types.py` · `ToolRegistry` (Protocol) + `EMPTY_REGISTRY` | The registry surface the loop depends on (`is_empty`, `to_anthropic_spec`, `get`) without importing the tool framework. | Concrete impl is `tools/base.py:ToolRegistry`. |
| `caps.py` · `HardCaps` | Frozen limits: `max_iterations=10`, `max_tool_calls=20`, `max_wall_clock_s=60.0`, `max_output_tokens=2048`, `thinking_budget_tokens=1024`. | `get_hard_caps()` is the dependency. |
| `caps.py` · `check_caps(state, caps)` → `CapBreach | None` | Checks iterations, tool calls, wall clock, output tokens **in that order**. | Called at the top of each loop iteration, before the model call. |
| `cost.py` · `cost_usd_micros(usage, model_id)` | Per-call cost in microUSD from `_PRICING`. Adds web_search/web_fetch request fees ($10/1k). | **Raises `ValueError` for an unknown `model_id`** — a model with no `_PRICING` entry fails the turn. |
| `db.py` · `make_session_factory(engine)` / `get_db_factory(request)` | Session-per-write factory; each `async with db_factory() as db:` opens, commits (or rolls back), closes one session. | The loop does **not** use `Depends(get_db)` — a request-scoped session can't be held across a 60s turn under pgbouncer transaction mode, and audit rows must be durable mid-turn. |
| `errors.py` · `ErrorCode` | SSE-surfaced error codes (tool/model/internal/cancelled/cap/validation). | Stored on `agent_turns.error_code` and the `error` event. |
| `errors.py` · `to_error_code(exc)` | Maps exceptions to `ErrorCode` (rate-limit, ≥500/overload, connection, cancel, timeout, validation, else internal). | Signature is `BaseException` because `CancelledError` is one. |
| `anthropic_io.py` · `scrub_blocks` / `scrub_block` | Strip SDK-only fields (e.g. `parsed_output`) the API rejects as input, via `INPUT_FIELDS_BY_BLOCK_TYPE` allowlist. Unknown types pass through. | `thinking` keeps `signature` so it roundtrips within a turn. |
| `anthropic_io.py` · `to_anthropic_content(content_blocks)` | Convert persisted blocks back to Anthropic input. Keeps **only** `text`; **drops** `block_id`, `context`, `status`, `stock_card`, `thinking`. | Used when loading cross-turn history — the `context` block and tool/thinking output are lost across turns; the model saw `context` only via its turn-only `render_hint`. |
| `anthropic_io.py` · `append_time_context` / `mark_history_cache_breakpoint` | Shape the request `messages` for caching: append the live clock as a request-only block on the current user turn; mark the end of frozen prior-turn history as an ephemeral cache breakpoint. | Called once per turn from `initialize_turn`. Cache prefix order is `tools → system → messages`, so the clock must sit *after* the history breakpoint. |
| `anthropic_io.py` · `estimate_thinking_tokens` | Heuristic `len(text)//4` for the audit column (Anthropic gives no per-block breakdown). | — |

### Flow (`app/ai/runtime/flow/`)

| File · symbol | Purpose | Notes |
|---|---|---|
| `iteration.py` · `build_iteration_request(...)` | Build `messages.stream` kwargs: model/system/messages/max_tokens/thinking + combined `tools`. | `cache_control` on the last tool spec caches the tools array with the system prompt. Empty `tools` is omitted (Anthropic 400s on empty). |
| `iteration.py` · `run_one_iteration(...)` → `IterationOutcome` | One full iteration: build → stream → persist invocation → reconcile server tools → accumulate → route. Wraps the model call in a Langfuse `generation` span. | On stream exception → returns `break`/`error` with `to_error_code(exc)`. On `CancelledError` → flushes partial text + status pills, re-raises. Falls back to a minted ULID + `loop_text_block_id_fallback` warning if a persisted text block has no streamed `block_start`. |
| `iteration.py` · `_decide_after_response(...)` | The `stop_reason` router (see lifecycle step 8.7). | A `tool_use` stop with **zero** tool_use blocks → `INTERNAL_ERROR` break (would otherwise loop forever). |
| `stream_consumer.py` · `StreamConsumer` | Per-iteration. Owns stream-time state (`open_text_blocks`, `open_thinking_blocks`, `accumulated_text`); emits SSE block events; polls `disconnect_check` every 16th text delta. | Closes the upstream stream eagerly on cancel. `redacted_thinking` emits a one-shot complete block. Server-tool start/result chunks delegate to the shared `ServerToolTracker`. |
| `stream_consumer.py` · `flush_partial_text(...)` | Append in-flight text partials to `assistant_blocks` on cancel (since `get_final_message` never returns mid-stream). | — |
| `turn_lifecycle.py` · `initialize_turn(...)` | Persist user message (+`context` block), load history → `messages`, append the request-only time-context block + mark the history cache breakpoint, open `agent_turns` row. Returns `(turn_id, messages)`. | User message persisted **first** so a mid-turn crash doesn't lose input. `TurnStarted` is emitted by the caller, not here. |
| `turn_lifecycle.py` · `TurnTotals` | Running token/cost counter accumulated across iterations. | Written to `agent_turns.total_*` at finalize. |
| `turn_lifecycle.py` · `finalize_turn_row(...)` | Append assistant message (if any blocks) + `complete_agent_turn`. | Run under `asyncio.shield`; errors are logged, never re-raised (the row is the last signal left). |
| `turn_lifecycle.py` · `emit_terminal_frame(...)` | Emit `Error` if `error_code` set, else `TurnCompleted`. | Only called on `completed_normally`. |

### Dispatch (`app/ai/runtime/dispatch/`)

| File · symbol | Purpose | Notes |
|---|---|---|
| `custom.py` · `dispatch_tool_uses(...)` → `ToolDispatchOutcome` | Run every `tool_use` block in parallel via `asyncio.gather`. Aggregates `tool_result_blocks`, `ui_block_dicts`, `tool_call_count`, and the **first** `terminal_error_code` (siblings still finish + write audit rows). | — |
| `custom.py` · `_dispatch_one_tool_use(...)` | Lookup → validate (`tool.Input.model_validate`) → execute → persist `tool_executions` row → emit wire events. Every exit path writes exactly one audit row. | Lookup miss → `INTERNAL_ERROR`; validation fail → `VALIDATION_ERROR`; execute raise → `TOOL_ERROR`. JSON-encodes `model_payload` into the `tool_result.content`. |
| `custom.py` · `RecordingEmitter` | Wraps the emitter, records `BlockStart` block_ids so the result branch knows whether a tool already announced its UI block inline (dedup). | A tool that emits its own `BlockStart` (e.g. `get_stock_info`) won't get a duplicate; `display_stock_card` emits nothing, so dispatch sends both `BlockStart` + `BlockEnd`. |
| `server.py` · `ServerToolTracker` | Turn-scoped. Pairs hosted-tool uses with results across iterations; renders/updates the status pill; writes `tool_executions` rows; `flush_orphans` closes unmatched uses (failed pill + `status=error` row). | `mark_active_failed` flips live pills to `failed` on cancel (shared refs with `assistant_blocks`). Orphans/dump failures emit Sentry warnings. |
| `server.py` · `build_server_tool_specs(config)` | Build the date-pinned hosted-tool specs (`web_search_20250305`, `web_fetch_20250910`, `code_execution_20250825`). | Bumping a version pin opts into Anthropic behavior changes. |
| `server.py` · `truncate_for_audit(value, 2000)` | Clip oversize payloads before the audit write. | `_preview` is debug-only. |

### Tools (`app/ai/tools/`)

The two portfolio read tools each have a dedicated reference — [`tools/get_portfolio.md`](tools/get_portfolio.md) and [`tools/get_portfolio_performance.md`](tools/get_portfolio_performance.md) (they share `utils/portfolio_tool_runtime.py`); the rows below are the harness-level summary.

| File · symbol | Purpose | Contract / Notes |
|---|---|---|
| `base.py` · `Tool[InputT]` (ABC) | Base for registered tools. ClassVars `name`, `description`, `Input` (a `BaseModel`); `async execute(input, ctx) -> ToolResult`. | The loop validates input against `Input` before calling `execute`. |
| `base.py` · `ToolResult` | `model_payload` (back to Anthropic), `ui_block: Block | None` (to the user), `internal_trace` (audit only). | `protected_namespaces=()` to allow the `model_payload` field name. |
| `base.py` · `ToolContext` | Injected into `execute`: `user_id`, `db_factory`, `sse_emitter`, `http_clients`, and an **unused** `parent_emitter` (sub-agent scaffolding). | — |
| `base.py` · `ToolHttpClients` | `market_data` (None without `FMP_API_KEY`) plus `alpaca` / `redis` (back the portfolio tools; None only when booted without a lifespan). All `… | None`. | Extend here to give tools more outbound clients. |
| `base.py` · `ToolRegistry` | `register(tool)` (rejects dupes), `get(name)`, `is_empty`, `to_anthropic_spec()` (caches the array tail). | Concrete impl of the `types.py` Protocol. |
| `__init__.py` · `build_default_registry()` / `DEFAULT_REGISTRY` | Registers `GetStockInfo` + `DisplayStockCard` + `RadarOperations` + `GetPortfolio` + `GetPortfolioPerformance`. | Module-level singleton used by `post_turn`. |
| `_performance.py` · `change_for_range(...)`, `bars_from_chart`, `PERFORMANCE_RANGES` | Shared change-over-range math so model prose and the iOS card can't drift. | `1D` uses FMP daily change; longer ranges diff first bar to price. |
| `stock_info.py` · `GetStockInfo` | Read live quote/profile/ratios/analyst for one ticker; returns data to the model. Emits a "Pulling data on X" pill (active→complete/failed). | Data goes to `model_payload`, plus the completed pill as `ui_block`. Fetches info + all range charts concurrently; degrades per-range on failure. |
| `display_stock_card.py` · `DisplayStockCard` | Render the inline visual card (logo, price, chart, optional stats). Pre-fetches bars for every range. | Emits no pill itself; returns a `StockCardBlock` as `ui_block`. Only the initial range is load-bearing. |
| `radar_operations.py` · `RadarOperations` | Read/add/remove on the user's radar via `RadarService` (adds land starred/user-added). `get` returns each item's human/ai source + AI-pick reason (`context_blurb`); pill "Looking at your Radar". add/remove emit "Adding/Removing $TICKER …". All active→complete/failed. | `operation` is `get`/`add`/`remove`; `symbol` required for add/remove only. Idempotent: duplicate add → `already_on_radar`, absent remove → `not_on_radar` (both complete, not errors). Reuses the radar service/repository; no new wire `Block`. |
| `portfolio.py` · `GetPortfolio` | Read the user's balances + holdings: an `overview` rollup (largest holdings by weight + concentration note), the full `positions` list (20 largest with per-position cost basis + unrealized P/L; the rest as bare tickers in `omitted_symbols`), or specific `symbols`. Snapshot + holdings fetched concurrently. Emits a "Reading your portfolio" pill. | Expected failures (no active account, broker down, deps missing) return `{"error","code"}` in `model_payload` — never raises, never ends the turn. Reuses `PortfolioService`; no new wire `Block`. Full detail: [`tools/get_portfolio.md`](tools/get_portfolio.md). |
| `portfolio_performance.py` · `GetPortfolioPerformance` | Read account value over a `range` (1D–ALL): start/end value, gain abs/pct, high/low, and a `trend` series downsampled to ≤16 points. Emits a "Reading your performance" pill. | Wraps `PortfolioService.get_history` (60s Redis cache, so ~60s stale). Same `{"error","code"}` failure contract as `get_portfolio`. Full detail: [`tools/get_portfolio_performance.md`](tools/get_portfolio_performance.md). |

### Transport (`app/ai/transport/`)

| File · symbol | Purpose | Notes |
|---|---|---|
| `events.py` · `Event` union | `TurnStarted`, `Status`, `BlockStart`, `TextDelta`, `BlockData`, `BlockEnd`, `TurnCompleted`, `Error`. Each carries a ULID `id`. | **Hand-mirrored by iOS.** `Status` is defined but **never emitted** anywhere. Block payloads ride as opaque dicts so transport doesn't depend on `blocks.py`. |
| `events.py` · `serialize` / `parse_wire_frame` | Render/parse the SSE frame (`id:`/`event:`/`data:`). `parse_wire_frame` cross-checks the `id:`/`event:` lines against the JSON. | The route actually serializes via `sse_starlette.ServerSentEvent`, not `serialize()` — `serialize`/`parse_wire_frame` are used by tests and any non-starlette consumer. |
| `emitter.py` · `SSEEmitter` | Single-consumer bounded `asyncio.Queue` (size 64). `emit` blocks when full (backpressure); `close()` pushes a `None` sentinel; `iter_events()` yields until the sentinel. | `emit` after `close` raises. Backpressure is why the route must cancel the driver on disconnect — otherwise the loop blocks forever on a full queue. |
| `idempotency.py` · `claim_idempotency` / `mark_complete` / `mark_failed` | Redis slot `ai:idem:{user_id}:{key}`: `SET NX` to claim (2-min TTL), flip to `complete` (24h TTL) on success, `DEL` on failure. | Returns `IdempotencyClaim(status, turn_id)`. Crashed in-flight claims self-heal via TTL; unrecognized values fall through to `in_flight` (409 over double-run). |

### Observability & prompts

| File · symbol | Purpose | Notes |
|---|---|---|
| `observability/langfuse.py` · `create_langfuse_client(settings)` | Real `Langfuse` when both keys are set, else `_NoopLangfuse`. `LangfuseClient = Langfuse | _NoopLangfuse`. | The loop sets `trace_id = turn_id.hex` so a trace looks up by `agent_turns.id`. Spans: `agent_turn` (agent) → `anthropic.messages.create` (generation per iteration). |
| `prompts/__init__.py` · `SystemPrompt` (`text`, `hash`) | Loads `sevino_v1.md`, sha256-hashes it. `system_prompt_for(server_tools)` returns the base or base+addendum (separately hashed). | `prompt_hash` is stored on `agent_turns`/`model_invocations` and tagged on the Langfuse trace, so prompt revisions are queryable. |

### Persistence & wiring (outside `ai/`)

| File · symbol | Purpose |
|---|---|
| `routes/conversations.py` · `post_turn`, `_drive_turn`, `_stream`, `_replay_turn` | HTTP endpoint; idempotency gate; detached driver task; SSE generator; persisted-turn replay. Also `list_conversations`, `list_conversation_messages`, `delete_conversation`. |
| `repositories/conversation.py` · `ConversationRepository` | All audit-trail DB access: `append_user_message`/`append_assistant_message` (maintain denormalized `last_message_at`/`title`), `load_history`, `start_agent_turn`, `complete_agent_turn` (partial update), `record_model_invocation`, `record_tool_execution`, `load_assistant_message_for_turn`, list/delete. Each method flushes but does not commit — the `db_factory` owns the transaction. |
| `models/*.py` | `Conversation` → `Message` (JSONB `content_blocks`); `AgentTurn` (terminal_state, error_code, totals); `ModelInvocation` (per-iteration request/response + tokens); `ToolExecution` (per tool call, self-referential `parent_tool_execution_id`). |
| `lifecycle.py` · `lifespan` | Builds `app.state.anthropic`, `app.state.langfuse`, `app.state.db_factory`, `app.state.market_data` (+ its own Redis on db=1). |

---

## 5. State & context management

**Conversation history.** Persisted in Postgres `messages.content_blocks` (JSONB). At turn start, `initialize_turn` calls `load_history` (all messages, oldest first) and maps each through `to_anthropic_content` into the in-memory `messages` list. History is therefore reconstructed from the database every turn; there is no in-process conversation cache.

**What `to_anthropic_content` keeps vs. drops.** Only `text` survives. A `context` block (user-attached modal data) is **dropped** along with `status`, `stock_card`, and `thinking` — so across turns the model sees prior assistant **text** but not its tool outputs or reasoning. The `context` block reached the model only on its own turn, via the turn-only `render_hint` appended to that user message.

**Within a turn**, the in-memory `messages` list is the live context window. After each model call, the full `response_content` (text + tool_use + **thinking with signatures**, post-`scrub_blocks`) is appended as an `assistant` message; tool results are appended as a `user` message. This is what lets thinking signatures roundtrip byte-for-byte across `pause_turn`/`tool_use` continuations.

**Prompt caching.** The cache prefix is ordered `tools → system → messages`, and a breakpoint hits only if every byte before it is unchanged. Three `cache_control: ephemeral` breakpoints are set per request (3 of Anthropic's 4 max), all sharing the 5-minute TTL:

- **System prompt** — loaded once at import from `prompts/sevino_v1.md` (+ optional server-tools addendum), hashed, and sent as a single `system` text block. Stable across turns.
- **Tools array tail** — the last entry of the combined `tools` array is cache-marked, extending the cached prefix over the tool specs.
- **Prior-turn history** — `mark_history_cache_breakpoint` marks the last block of the last frozen history message, so the replayed conversation cache-reads across turns (set in `initialize_turn`).

The live **time context** (clock + market status) is appended to the **current user message**, *after* the history breakpoint — so its per-turn value never invalidates the cached prefix. (It was previously a second `system` block, which sat ahead of `messages` in the prefix and would have blocked history caching.)

**Persisted vs. ephemeral:**

| Data | Persisted? | Where |
|---|---|---|
| User message (text + context block) | Yes | `messages` |
| Assistant text blocks | Yes | `messages` (`assistant_blocks`) |
| Tool UI blocks (`status`, `stock_card`) | Yes | `messages` (`assistant_blocks`) |
| Thinking blocks | **No** | Streamed live only; lost on reload |
| Per-iteration request/response + tokens | Yes | `model_invocations` |
| Each tool call (input/output/trace/latency) | Yes | `tool_executions` |
| Turn outcome + token/cost totals | Yes | `agent_turns` |
| Idempotency slot + turn_id | Yes (TTL'd) | Redis |
| Langfuse trace | Yes (if keyed) | Langfuse, keyed by `turn_id.hex` |

There is **no memory subsystem** — no summarization, no vector store, no cross-conversation recall. Context is exactly the (possibly long) message history of one conversation, replayed in full each turn. Long conversations grow the input unbounded until they hit Anthropic's context limit; nothing trims them.

---

## 6. Tool / function-calling layer

### Two kinds of tools

1. **Registered (custom) tools** — local `Tool` subclasses in `tools/`, dispatched by `dispatch/custom.py` on the `tool_use` stop reason.
2. **Hosted (server) tools** — Anthropic-run `web_search` / `web_fetch` / `code_execution`, declared in the request and reconciled by `dispatch/server.py`. They never execute local code; the harness only tracks their pills and writes audit rows.

### The contract a custom tool must satisfy

```python
class MyTool(Tool[MyInput]):
    name: ClassVar[str] = "my_tool"            # unique registry key + Anthropic tool name
    description: ClassVar[str] = "..."         # sent to the model as the tool description
    Input: ClassVar[type[BaseModel]] = MyInput # JSON schema via .model_json_schema()

    async def execute(self, input: MyInput, ctx: ToolContext) -> ToolResult:
        ...
        return ToolResult(model_payload={...}, ui_block=SomeBlock(...), internal_trace={...})
```

- **Definition:** subclass `Tool[InputT]`, set the three ClassVars, implement `execute`.
- **Registration:** `registry.register(MyTool())` — done in `build_default_registry()` (`tools/__init__.py`). Duplicate names raise.
- **Spec generation:** `ToolRegistry.to_anthropic_spec()` emits `{name, description, input_schema}` per tool, caching the last entry. `build_iteration_request` concatenates server-tool specs + registry specs and sends them every iteration.
- **Selection:** the model picks tools by name; the harness does no pre-filtering. Every registered tool is offered on every turn.
- **Execution:** on a `tool_use` stop, `dispatch_tool_uses` runs all blocks in parallel. Per tool: `tool.Input.model_validate(raw_input)` (failure → `VALIDATION_ERROR`, audit row, no execute), then `execute(validated, ctx)` (any raise → `TOOL_ERROR`, audit row). Unknown tool name → `INTERNAL_ERROR`.
- **Result re-entry:** `model_payload` is `json.dumps`'d into a `tool_result` block keyed by `tool_use_id`, collected into one follow-up `user` message, and the loop **continues** — the model sees the results on the next iteration. `ui_block` is emitted to SSE (`BlockStart`/`BlockEnd`, deduped via `RecordingEmitter`) and appended to the persisted `assistant_blocks`. `internal_trace` goes only to the `tool_executions` row.
- **Side effects available via `ctx`:** open DB sessions (`ctx.db_factory`), emit interim SSE (`ctx.sse_emitter` — e.g. an "active" pill before the work completes), and call outbound services (`ctx.http_clients`).

Error isolation: one tool's failure sets the iteration's terminal error code but does **not** cancel its siblings — they finish and write audit rows. The first error in input order wins.

---

## 7. Configuration & dependencies

### Models

- **Main:** `settings.anthropic_model_main` (env `ANTHROPIC_MODEL_MAIN`, default `claude-sonnet-4-6`). Wired via `get_default_model_config()`.
- **Smoke:** `claude-haiku-4-5-20251001` (fixed, CI).
- `cost.py:_PRICING` has entries for `claude-sonnet-4-6`, `claude-opus-4-7`, `claude-haiku-4-5-20251001`. **A model without an entry raises `ValueError` mid-turn** → the turn errors out. Adding a model means adding pricing.

### Environment variables (in `app/config.py`)

| Var | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic client auth. |
| `ANTHROPIC_MODEL_MAIN` | `claude-sonnet-4-6` | Main model id. |
| `ANTHROPIC_ENABLE_WEB_SEARCH` | `False` | Enable hosted `web_search` for all turns. |
| `ANTHROPIC_ENABLE_WEB_FETCH` | `False` | Enable hosted `web_fetch`. |
| `ANTHROPIC_ENABLE_CODE_EXECUTION` | `False` | Enable hosted `code_execution`. |
| `ANTHROPIC_WEB_SEARCH_MAX_USES` | `5` | Per-turn cap passed in the tool spec. |
| `ANTHROPIC_WEB_FETCH_MAX_USES` | `5` | Per-turn cap. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | `""` | Both must be set or Langfuse is a no-op stub. |
| `LANGFUSE_HOST` | `https://us.cloud.langfuse.com` | Langfuse endpoint. |
| `FMP_API_KEY` | (required field) | When empty, `app.state.market_data` is `None` and the stock tools degrade gracefully. |

Server-tool flags are **global** (per-deployment), not per-user or per-conversation. `post_turn` reads them off `settings` into a fresh `ServerToolsConfig` each request.

### External services

- **Anthropic** (`AsyncAnthropic`) — the LLM, via streaming `messages.stream`.
- **Postgres** (async SQLAlchemy via `db_factory`) — all persistence.
- **Redis** — idempotency slots (the ARQ pool's Redis, `app.state.arq`).
- **Langfuse** — tracing (optional).
- **FMP / Alpaca** (via `MarketDataService`) — market data for the stock tools.

### Wiring (`lifecycle.py`)

`lifespan` populates `app.state.anthropic`, `app.state.langfuse`, `app.state.db_factory` (from the shared `engine`), and `app.state.market_data` (only if `FMP_API_KEY`; on its own Redis db=1). FastAPI dependencies (`get_anthropic`, `get_langfuse`, `get_db_factory`, `get_idempotency_redis`, `get_default_model_config`, `get_hard_caps`) read these and inject them into `post_turn`, which passes them to `run_agent_turn`.

---

## 8. Extension points

### Adding a tool

1. Create `tools/my_tool.py` with a `Tool[InputT]` subclass (`name`/`description`/`Input`/`execute`).
2. Register it in `build_default_registry()` (`tools/__init__.py`).
3. If `execute` returns a **new block type**, add it to the `Block` union in `blocks.py` **and** mirror it in iOS (`Block.swift`) — there is no codegen and no CI check; drift breaks the iOS decoder at runtime. Also teach `_replay_turn` and `to_anthropic_content` how to handle the new type (today they only special-case `text`/`context`).
4. If the tool needs a new outbound client, add it to `ToolHttpClients` and populate it in `lifecycle.py` + `post_turn`.

No loop changes are required — dispatch, validation, audit, and SSE are generic over `Tool`.

### Adding middleware / cross-cutting behavior

The loop has no formal middleware concept. The established seams:

- **Emitter wrapping** (the `RecordingEmitter` pattern in `dispatch/custom.py`) — wrap `SSEEmitter` to observe or rewrite outbound events (e.g. PII redaction on `text_delta`, metrics). Inject the wrapper where the emitter is constructed (`post_turn`) or where `ToolContext` is built.
- **Per-iteration hook** — add a check in the `while True` body of `run_agent_turn` next to `check_caps` / `disconnect_check` (e.g. a per-user token budget, a kill switch).
- **Per-tool hook** — wrap `_dispatch_one_tool_use` in `dispatch/custom.py` (e.g. authorization, rate limiting per tool).
- **Per-request hook** — before `run_agent_turn` in `post_turn` (e.g. content policy on the inbound message).

### Adding a skill system

A "skill" is naturally a bundle of (a) a prompt fragment, (b) a set of tools, and (c) activation rules. The codebase already contains a working template for an optional, composable capability: **server tools.** Server tools demonstrate the full vertical slice — a config object, a prompt addendum, spec injection, and dispatch/tracking. A skill system should mirror that slice:

1. **Prompt composition — `prompts/__init__.py`.** `system_prompt_for(server_tools)` already composes a base prompt with an addendum and re-hashes. Generalize this to compose N skill fragments: `system_prompt_for(server_tools, skills)`. Each active skill contributes a markdown fragment; the combined text gets a fresh `prompt_hash`, which already flows to `agent_turns`, `model_invocations`, and the Langfuse trace — so skill activation becomes queryable for free. **This is the cleanest insertion point for the prompt half.**

2. **Tool grouping & per-turn registry — `tools/`.** Today `DEFAULT_REGISTRY` is a module-level singleton offering all tools every turn. Skills imply a *subset* of tools active per turn/user, so replace the singleton with a per-turn `build_registry(active_skills)` that registers only the selected skills' tools. The `ToolRegistry`/`Tool` contract needs no change. Define a `Skill` as `{name, prompt_fragment, tools: list[Tool], is_enabled(ctx) -> bool}`.

3. **Selection plumbing — `routes/conversations.py` → `run_agent_turn`.** Mirror `server_tools_config`: resolve the active skills in `post_turn` (from user settings, feature flags, or the request), pass a `skills`/`registry` argument through `run_agent_turn` into `build_iteration_request` and `system_prompt_for`. `run_agent_turn` already takes `tool_registry` and `system_prompt` as parameters — so per-turn selection requires no signature change to the loop itself, only different arguments from the route.

4. **Sub-agent skills (optional, future) — `dispatch/` + `loop.py`.** The schema and runtime already anticipate sub-agents: `ModelInvocation.agent_role` (defaults `"main"`), `ToolExecution.parent_tool_execution_id`, the unused `ToolContext.parent_emitter`, and the loop's "runs in sub-agents" design note. A skill that spawns a child agent would have its tool's `execute` call `run_agent_turn` again with a child emitter (feeding `parent_emitter`), a child registry, and `agent_role` set to the skill name. The audit trail is already shaped for this; the wiring (child emitter multiplexing onto the parent SSE stream, recursion-depth caps) is not yet built.

**Smallest viable skill system:** items 1–3. Add a `skills/` package alongside `tools/`, a `Skill` dataclass, a `resolve_active_skills(user, request)` in the route, and generalize `system_prompt_for` + the registry builder. The loop, dispatch, transport, and persistence layers are untouched.

---

## 9. Architectural observations

Honest notes on coupling, assumptions, and fragility — the places to push on.

**Hidden iOS coupling, enforced by nothing.** `blocks.py` and `transport/events.py` are hand-mirrored in Swift with no codegen and no CI check (called out in `CLAUDE.md`). Any new block/event variant or field silently breaks the iOS decoder at runtime. The cross-layer contract is the single most fragile thing here.

**Replay and history only understand `text`.** `_replay_turn` (route) skips non-text blocks, and `to_anthropic_content` drops `status`/`stock_card`/`thinking`. Consequences: (a) an idempotent replay of a turn that produced a stock card re-emits **only the text** — the card silently vanishes on retry; (b) across turns the model has no memory of its own tool outputs. Any richer persisted block type must update both functions or it degrades invisibly.

**Thinking is never persisted.** Thinking streams live but isn't written to `messages`. Reloading a conversation loses all reasoning, and the model can't see its prior thinking across turns (only within a turn via the in-memory `messages`). This is deliberate but worth knowing.

**No context-window management.** History is replayed in full every turn with no summarization or trimming. Long conversations grow input tokens monotonically until they hit the model's context limit, at which point Anthropic 400s and the turn errors. There is no guardrail for this today.

**`disconnect_check` is dead in production.** It is hardwired to `None` by the route because `BaseHTTPMiddleware` consumes the ASGI receive channel upstream, so `request.is_disconnected` never fires. Cancellation relies entirely on `EventSourceResponse` calling `task.cancel()` when the SSE generator closes. The polling path exists only for tests. If the cancel-on-generator-close behavior ever changes, disconnects would leak in-flight Anthropic calls until the wall-clock cap.

**Cancellation correctness rests on `asyncio.shield`.** `finalize_turn_row` and the idempotency `mark_*` calls are shielded because sse-starlette's teardown re-cancels the parent before commits land. This is subtle and load-bearing: a regression that drops a shield reintroduces stuck `in_flight` slots and non-terminal `agent_turns` rows. The logic is correct but depends on framework teardown ordering that isn't obvious.

**Unknown model id fails the turn, not loudly at startup.** `cost_usd_micros` raises `ValueError` for a model with no `_PRICING` entry. Since pricing is checked per-invocation (not at config load), setting `ANTHROPIC_MODEL_MAIN` to an unpriced model boots fine and then errors every turn. A startup validation would catch this earlier.

**Dead/partial scaffolding.** The `Status` event is defined but never emitted. `ToolContext.parent_emitter` is never read. `record_model_invocation` is never passed `request_tools`, so that JSONB column is always NULL despite existing. `agent_role`/`parent_tool_execution_id` exist for sub-agents that aren't built. None of this is wrong, but it's surface area that reads as "supported" and isn't.

**Server-tool reconciliation is best-effort and Sentry-noisy.** `ServerToolTracker` pairs uses with results by `tool_use_id` across iterations; orphans (use without result), orphan results (result without use), and content-dump failures each log + capture a Sentry warning and write a degraded audit row. It never fails the turn, but the audit trail for hosted tools can be lossy under contract violations, and the pill state on cancel depends on shared dict references (`mark_active_failed`) — easy to break with a refactor that copies instead of mutates.

**Per-write sessions multiply round-trips.** `db_factory` opens a fresh session+commit per audit write (user message, history load, turn start, each invocation, each tool execution, finalize). This is the right call under pgbouncer transaction mode and for mid-turn durability, but a multi-tool, multi-iteration turn issues many short transactions; there's no batching knob.

**Global, all-or-nothing tool offering.** Every registered tool is sent on every turn, and server tools are a per-deployment flag. There is no per-user/per-conversation tool gating today — the reason a skill system needs new selection plumbing (§8) rather than a config tweak.

**Idempotency is user-scoped, not conversation-scoped.** Slots key on `(user_id, idempotency_key)`. Reusing a key against a different conversation is caught only in the replay path (`load_assistant_message_for_turn`'s `conversation_id` check → `IDEMPOTENCY_CONVERSATION_MISMATCH`), i.e. after the claim. Correct, but the mismatch is detected late.
