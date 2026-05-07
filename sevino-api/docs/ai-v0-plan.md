# Sevino AI Agent Infrastructure — v0 Implementation Plan

**Audience:** Sevino engineering, week-of planning.
**Scope:** v0 rails only. One real tool (`get_stock_info`). End state: iOS sends "how is AMD doing" → SSE stream returns text + status pill + live `StockCardBlock` rendered in chat. Full audit in Postgres, traces in Langfuse, idempotent + cancellable.
**Author note:** Decisions answered ahead of writing this plan: in-place schema migration of existing `conversations`/`messages` tables (empty); Alpaca Market Data sandbox (creds to acquire); CI scaffolded in Phase 1; Linear convention `AI — [subdiscipline]`; Home view IS the chat surface (message-list slots in above the existing input bar); conversations created implicitly on first turn.

---

## 1. Gap analysis

Items numbered to match the v0 component checklist (1–28). Status legend:
- 🟢 **Exists, reuse as-is** — no work
- 🟡 **Partial** — extends or wraps existing code
- 🔴 **Greenfield** — net-new

### Backend — runtime core

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 1 | Anthropic SDK plumbing | 🔴 | No `anthropic`, `openai`, or `langchain` imports anywhere. No `ANTHROPIC_API_KEY` in `.env.example` (`sevino-api/.env.example:44-65`). | Add `anthropic` to `pyproject.toml`. New `app/ai/anthropic_client.py` mirroring `services/alpaca_broker.py` shape: singleton instantiated in `app/lifecycle.py:10-22`, attached to `app.state.anthropic`, `Depends(get_anthropic)` in routes, `await client.aclose()` in shutdown. Constants module `app/ai/models.py` with `MODELS.SONNET = "claude-sonnet-4-..."` etc. New env vars: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_MAIN` (defaults to Sonnet pinned). Add to `.env.example` + `app/config.py:37-111` `Settings`. |
| 2 | Versioned system prompt | 🔴 | No `app/ai/prompts/` directory. | New file `app/ai/prompts/sevino_v1.md`. Loader in `app/ai/prompts/__init__.py`: read at import-time, `prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()`. Hash persisted on every `agent_turns` row. |
| 3 | Agent loop module | 🔴 | None. | New `app/ai/runtime/loop.py`. Pure async function `run_agent_turn(*, user_id, conversation_id, user_message, sse_emitter, db, tool_registry, system_prompt, model_config, hard_caps) -> AgentTurnResult`. No FastAPI imports. Parameterised so a future sub-agent is just the same function called with a different system prompt + tool registry. |
| 4 | Extended thinking | 🔴 | None. | Inside loop: pass `thinking={"type": "enabled", "budget_tokens": 1024}` to Anthropic. On iteration N+1, pass prior assistant content **including thinking blocks with signatures**. Track `total_thinking_tokens` separately on `agent_turns`. |
| 5 | Tool framework | 🔴 | None. | New `app/ai/tools/`: `Tool` ABC (name, description, `Input: type[BaseModel]`, `async execute(input, ctx) -> ToolResult`), `ToolResult(model_payload, ui_block, internal_trace)`, `ToolContext(user_id, db, sse, http_clients, parent_emitter)`, `ToolRegistry.to_anthropic_spec()`. |
| 6 | `get_stock_info` tool | 🔴 | No Alpaca Market Data integration anywhere — confirmed via grep across whole backend. | Two-layer split: (a) generic Alpaca Market Data client `app/services/alpaca_market_data.py` (sibling of `alpaca_broker.py`), authenticated with new `ALPACA_DATA_API_KEY_ID` + `ALPACA_DATA_SECRET_KEY` (separate from broker OAuth), sandbox base URL `https://data.sandbox.alpaca.markets`. Methods: `get_latest_quote(symbol)`, `get_bars(symbol, timeframe, start, end)`. (b) Tool wrapper `app/ai/tools/get_stock_info.py` returning small payload to model, full `StockCardBlock` to UI, raw responses in `internal_trace`. Range param: `Literal["1D","1W","1M","3M","6M","1Y","ALL"]`. |
| 7 | Block schemas | 🔴 | None. | New `app/ai/blocks.py`: discriminated union `Block = TextBlock \| StatusBlock \| StockCardBlock` via Pydantic `Field(discriminator="type")`. Mirrors iOS `enum Block`. |
| 8 | Hard caps | 🔴 | None. | `HardCaps` dataclass in `app/ai/runtime/caps.py`: `max_iterations=10, max_tool_calls=20, max_wall_clock_s=60, max_output_tokens=2048`. Loop checks at every iteration boundary. Each cap maps to a distinct `terminal_state` value. |

### Backend — persistence

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 9 | Alembic migration | 🟡 | `conversations` and `messages` tables EXIST in `migrations/versions/b4900a105d3f_initial_migration.py` with non-target schema; user confirmed empty. `order_events.conversation_id` FK is load-bearing (trade history). `agent_turns`, `model_invocations`, `tool_executions` do not exist. Migration head is `c8d2fa74e103` (single head, clean). | One new migration `add_agent_runtime_tables.py`. **Existing tables (in-place ALTER, safe because empty):** `conversations`: drop `preview`, drop `started_at`, add `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. `messages`: drop `content`, `mcp_cards`, `tool_calls`; add `content_blocks JSONB NOT NULL DEFAULT '[]'::jsonb`. Keep `order_events.conversation_id` FK untouched. **New tables:** `agent_turns`, `model_invocations`, `tool_executions` per spec, with `agent_role` (default `"main"`) and `parent_tool_execution_id` self-FK from day one. Use TEXT for `terminal_state` and `status` enums (matches existing convention — no `PgEnum` used anywhere in the codebase, see `plaid_items.status`, `ach_relationships.status`). |
| 10 | `ConversationRepository` | 🟡 | No conversation/message repository today; existing repository pattern is clear (`@staticmethod`, `db: AsyncSession` first arg, no instance state — see `repositories/user_profile.py`, `repositories/financial_profile.py`). | New `app/repositories/conversation.py` with `@staticmethod` methods: `create_conversation`, `load_history`, `append_user_message`, `append_assistant_message_with_blocks`, `start_agent_turn`, `complete_agent_turn`, `record_model_invocation`, `record_tool_execution`. Each write uses its own short transaction (explicit `await db.commit()` per write, NOT relying on the request-end auto-commit) — required because the streaming turn must not hold a transaction across iterations. |
| 11 | Cost calculator | 🔴 | None. | `app/ai/runtime/cost.py`: `cost_usd_micros(usage, model_id) -> int`. Rate table per model (input, output, cache read, cache write, thinking). Called per `model_invocation`, summed at end of turn. |

### Backend — transport

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 12 | SSE event protocol | 🔴 | `httpx-sse` is installed (used by Alpaca consumer in `listeners/base_sse.py`). `sse-starlette` is NOT in deps. No server-side SSE pattern exists yet — the listeners *consume* SSE, they don't *serve* it. | New `app/ai/transport/events.py`: Pydantic discriminated union of event variants (`TurnStarted, Status, BlockStart, TextDelta, BlockData, BlockEnd, TurnCompleted, Error`). Wire-format serializer producing `id: <ulid>\nevent: <type>\ndata: <json>\n\n`. Stable `id:` per event from day one (full resume is post-v0). |
| 13 | Chat turn endpoint | 🔴 | None. | New `app/routes/conversations.py` registered at `prefix="/v1/conversations"`. `POST /v1/conversations/{id}/turns` body `{message: str, idempotency_key: str}`, returns `text/event-stream`. Behind existing JWT (`Depends(get_current_user)` works fine on streaming responses — proven by `app/routes/settings.py:107-126`). slowapi: start at `30/minute` per user via `@limiter.limit("30/minute")`. **Decision:** use `sse-starlette`'s `EventSourceResponse` (add to deps) — it handles client-disconnect + ping correctly so we don't reinvent that. |
| 14 | `SSEEmitter` abstraction | 🔴 | None. | New `app/ai/transport/emitter.py`: `class SSEEmitter` holding an asyncio queue; agent loop calls `await emitter.emit(event)`. Endpoint glues queue → `EventSourceResponse`. Decoupled from FastAPI for testability and for future sub-agents (sub-agent receives parent's emitter). |

### Backend — safety

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 15 | Idempotency | 🔴 | No `Idempotency-Key` handling anywhere. | New `app/ai/transport/idempotency.py`. Redis is already configured (slowapi + ARQ). Logic per spec: not present → set `{status: "in_flight", turn_id, started_at}` 2-min TTL → run → on success update to `{status: "complete", turn_id, assistant_message_id}` 24h TTL; present + complete → replay persisted message as single SSE stream; present + in_flight → 409 Conflict. Wrap loop in `try/finally` to mark `failed` on crash. |
| 16 | Cancellation | 🔴 | No `request.is_disconnected()` / `ClientDisconnect` handling in any route. (Long-running listeners do handle `asyncio.CancelledError` — see `listeners/base_sse.py:142-162`.) | Two checks per spec: (a) at every iteration boundary in the agent loop; (b) inside the streaming callback when forwarding Anthropic deltas. On disconnect: close in-flight Anthropic stream (Anthropic SDK supports `await stream.close()`), mark turn `cancelled`, persist partial assistant message with whatever blocks completed. |
| 17 | Error taxonomy | 🔴 | None for AI; existing exception taxonomy in `app/exceptions.py` is the model. | New `app/ai/runtime/errors.py`: single `ErrorCode` enum (`tool_timeout, tool_error, model_overloaded, model_rate_limit, internal_error, cancelled, turn_iteration_limit, tool_call_limit, output_token_limit, validation_error`). One mapping function `to_error_code(exc) -> ErrorCode`. The `error` SSE event carries the code. iOS branches on the code, not the message. |
| 18 | Prompt caching | 🔴 | None. | One-line: mark system prompt block + tool definitions array with `cache_control: {"type": "ephemeral"}` in the Anthropic request. |

### Backend — observability

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 19 | Langfuse | 🔴 | None. | Add `langfuse` to deps. Singleton in `app/ai/observability/langfuse.py` initialised in `lifecycle.py`. Wrap every Anthropic call and every tool execution in spans. Tags: `user_id, conversation_id, turn_id, prompt_hash, environment`. **Recommendation: Langfuse Python SDK directly, not OTel** — the SDK has Anthropic-aware helpers (`@observe` decorator, automatic usage tracking) that OTel adapters lose. |

### Backend — dev experience

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 20 | Smoke harness | 🟡 | No `.github/workflows/` exists at all. | **Split across phases.** Phase 1: CI scaffold (`.github/workflows/ci.yml` running `make test` on every PR; no smoke yet). Phase 2: smoke cases for `"hello"` + iteration cap (real Anthropic, cheap model — Haiku — env-flagged via `RUN_AI_SMOKE=1`). Phase 3: third smoke case for AMD price query exercising `get_stock_info`. Smoke harness gated on `RUN_AI_SMOKE` secret to avoid bills on every contributor's PR — runs on `main` push. |

### iOS

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 21 | `SSEClient` actor | 🔴 | No SSE/WebSocket client in iOS. (`URLSessionWebSocketTask`, `URLSession.bytes`, `EventSource` — zero matches.) | New `Sevino/Services/Chat/SSEClient.swift`: actor built on `URLSession.bytes(for:)`. Line buffering, parses `event:`/`data:`/`id:`. Exposes `AsyncStream<SSEEvent>`. Header provider closure for auth (don't bake JWT — reuse the same pattern as `APIClient.swift:39-41` `tokenProvider`). API designed so reconnect can be added later without callers changing. |
| 22 | Typed event decoder | 🔴 | None. iOS already uses discriminated-union pattern for `OrderSide` (TradingDTOs.swift) — good reference. | New `Sevino/Models/Chat/SSEEvent.swift`: `enum SSEEvent: Decodable` with associated values per backend variant. Decode via custom `init(from:)` checking the `type` discriminator. Loud `os_log` decode-failure logging in DEBUG builds (don't crash; surface to Sentry equivalent). |
| 23 | Block-based message model | 🔴 | None. Current `ChatItem` (Models/Home/ChatItem.swift) is a stub for the recents sidebar — different concern. | New `Sevino/Models/Chat/Message.swift`: `struct Message { id: UUID; role: Role; var blocks: [Block] }`, `enum Block: Codable, Identifiable` matching backend. Each block addressable by `block_id` for delta patching. Use `@Observable` on the parent store (not the model) so SwiftUI re-renders incrementally. |
| 24 | `ConversationStore` | 🔴 | `HomeViewModel.swift` shows the right `@Observable` shape. `PlaceholderChatService` is a placeholder we'll replace. | New `Sevino/ViewModels/Chat/ConversationStore.swift`: `@Observable @MainActor final class ConversationStore`. Owns `messages: [Message]` and `state: TurnState`. Method `send(text:) async throws` opens an SSE stream via `SSEClient`, applies events to message list. No networking in views. Replaces `ChatService.swift` placeholder. |
| 25 | Chat view + 3 block renderers | 🟡 | Home is the chat surface. `HomeChatInputBar.swift` already handles input, ticker mentions (`TickerMentionViewModel`), dictation, and emits `[MessageSegment]` on send. The message list is the missing piece. | Three new renderer views: `Sevino/Views/Chat/Blocks/TextBlockView.swift` (markdown — see decision §4 for library), `StatusPillView.swift`, `StockCardView.swift` (real, matches design — Swift Charts for the line chart, range pills, progressive population as `block_data` events arrive). New `Sevino/Views/Chat/MessageListView.swift` rendering `[Message]` with one row per message, blocks inside a `VStack`. **Integration into Home:** add a `messages: [Message]` overlay in `HomeView` body that takes over the main content area when `conversationStore.messages.isEmpty == false` (chat fills home; suggestions/greeting hidden once conversation starts). The existing `HomeChatInputBar` stays put — wire its `onSend` callback into `conversationStore.send(...)`. |
| 26 | Auth integration | 🟢 | `AuthService.shared.accessToken` already returns the Supabase JWT (auto-refreshed by SDK). `APIClient.swift:39-41` shows the `tokenProvider` closure pattern. | Pass the same closure to `SSEClient` constructor: `tokenProvider: { await AuthService.shared.accessToken }`. Zero new auth code. |

### Cross-cutting

| # | Item | Status | Current state | What's needed |
|---|---|---|---|---|
| 27 | Shared schema artifact | 🔴 | None. | Generate JSON schema from Pydantic discriminated union at build time → committed at `sevino-api/app/ai/schema/v1.json`. **Recommendation: hand-mirror Swift, CI-diff** (see decision §4). New `make ai-schema-export` target writes the JSON; new `tests/ai/test_schema_in_sync.py` fails if Pydantic exports diverge from the committed JSON; iOS `enum Block` is hand-maintained but a CI check (in iOS CI when it lands) compares variant names against the JSON keys. |

---

## 2. Phase plan

The original spec suggested 2 phases. After examining dependencies and risk concentration, **3 phases is the better split.** The 2-phase version stacked ~17 items into Phase 1 (Anthropic streaming + persistence + SSE + idempotency + cancellation + observability all coupled) — if any one of those went sideways on day 5, the rest were entangled. The 3-phase split derisks the foundation in 2-3 days before adding chat-turn semantics on top, and it unblocks iOS work one phase earlier than the 2-phase version.

Each phase ends in a genuine end-to-end demo. Each phase derisks something distinct.

### Phase 1 — Foundation
**Goal:** Claude can talk to us, fully audited. No streaming yet — the response comes back after a few seconds as a single payload. The point is to prove the agent runtime, persistence, and observability work end-to-end before layering chat-turn semantics on top.

**Items:** 1, 2, 3, 4, 8, 9, 10, 11, 17, 18, 19, 20 — plus minimal CI scaffold (workflow file + `make test` gating PRs; smoke harness deferred to Phase 2).

**Proof-of-life milestones (must pass to call Phase 1 done):**
- ✅ `curl -d '{"message":"hi","idempotency_key":"x"}' http://localhost:8000/v1/conversations/$ID/turns` returns the full Claude response after a few seconds (synchronous, no SSE yet — temporary `application/json` response in this phase only).
- ✅ `agent_turns`, `model_invocations` rows in Postgres carry full request/response JSON including thinking blocks **with signatures intact**.
- ✅ Hitting the 60s wall-clock cap or 10-iteration cap (force via test prompt) ends gracefully with a terminal-state row, NOT a 500.
- ✅ Trace appears in Langfuse Cloud with cost in USD micros and the prompt hash tag.
- ✅ Migration applied cleanly to a fresh Supabase: existing `conversations`/`messages` tables ALTERed in place; new `agent_turns`/`model_invocations`/`tool_executions` tables present; `order_events.conversation_id` FK still valid.
- ✅ CI green on PR via `make test`.

**Rough size:** M (~2-3 days). Most novel work: getting Anthropic streaming + extended thinking + tool-use signature roundtripping right; getting the session-per-write DB pattern correct (§4 R2).

**Dependencies:** Anthropic API key + Langfuse Cloud account provisioned day 1.

### Phase 2 — Streaming + Safety
**Goal:** Real chat-turn semantics on top of the foundation. Same single text response, but now streamed via SSE, idempotent, and cancellable. No tools yet.

**Items:** 7-partial (TextBlock + StatusBlock skeletons only — full `StockCardBlock` deferred to Phase 3), 12, 13, 14, 15, 16, 21 (full smoke harness with first two cases — `"hello"` and iteration cap; AMD case waits for Phase 3).

**Proof-of-life milestones:**
- ✅ `curl -N -H "Idempotency-Key: $KEY" -d '…' …/turns` streams `event: text_delta` chunks live, then `event: turn_completed`.
- ✅ Same `Idempotency-Key` twice → second call replays the persisted message as a single SSE stream, no second Anthropic invocation.
- ✅ Different idempotency key with the in-flight one returns 409.
- ✅ Pressing Ctrl-C on the `curl` mid-stream marks the turn `cancelled` server-side within ~1s; partial assistant message persists with whatever blocks completed.
- ✅ Smoke harness runs the `"hello"` and iteration-cap cases against real Anthropic on `main` push (gated on `RUN_AI_SMOKE` secret); both pass.

**Rough size:** M (~2-3 days). The endpoint flips from JSON to SSE; idempotency middleware is net-new but bounded; cancellation requires careful coupling between `request.is_disconnected()` and Anthropic's stream `.close()`.

**Dependencies:** Phase 1 merged to `main` (the agent loop + persistence + repos + caps are reused as-is; only the response transport changes). Once Phase 2's SSE event protocol (item 12) is committed, **iOS work in Phase 3 can start in parallel** — the wire format is stable.

### Phase 3 — Tools + iOS
**Goal:** Full proof-of-life. iOS sends "how is AMD doing" from `HomeChatInputBar`, sees status pill ("Looking up AMD"), text streaming, and a real `StockCardBlock` rendered with live price + 30-day chart.

**Items:** 5, 6, 7-rest (`StockCardBlock` full schema), 21-rest (third smoke case — AMD price query exercising `get_stock_info`), 22, 23, 24, 25, 26, 27, 28.

**Proof-of-life milestones:**
- ✅ Backend: `curl` to `/turns` with `"how is AMD doing"` returns SSE stream with `block_start` for `status` ("Looking up AMD"), `block_end` for status, `block_start` for `stock_card`, `block_data` patches as quote + bars data arrives, `block_end`. `tool_executions` row has `internal_trace` populated with raw Alpaca quote + bars JSON, `ui_blocks_emitted` array contains the StockCardBlock, `upstream_api_calls` lists the two Alpaca data calls with status codes.
- ✅ iOS: app sends "how is AMD doing", message list takes over home content area, status pill appears, text streams, real `StockCardBlock` renders matching the design (price, % change, sparkline, 1D/1W/1M/3M/6M/1Y/ALL pills).
- ✅ Killing the iOS app mid-stream cancels the agent turn server-side within ~2s (`agent_turns.terminal_state = 'cancelled'`).
- ✅ Force-quit + reopen + retry with same idempotency key → message replays from persisted blocks, no re-billing.
- ✅ Generated JSON schema at `app/ai/schema/v1.json` matches Pydantic source; CI diff check passes.
- ✅ All three smoke cases pass on `main`.

**Rough size:** L (~4-5 days). Largest phase by line count, but **highly parallelisable** — tool framework + Alpaca Market Data integration on backend can run alongside SSE client + block models + UI on iOS as soon as the JSON schema is committed.

**Dependencies:** Phase 2 merged. Alpaca Market Data sandbox credentials provisioned. Markdown library decision made (§4 D5).

---

## 3. Resolved decisions

All twelve decisions are resolved. Recorded here as the canonical reference — diverging from any of these in implementation requires explicit re-discussion.

### D1. Alpaca Market Data — auth + feed level → **(a) Sandbox + IEX (free)**
v0 is dev-loop only; sandbox prices are good enough for proof-of-life. Production + SIP is an MVP-launch decision, not a v0 one (real cost item; belongs alongside legal disclaimers). New env vars: `ALPACA_DATA_API_KEY_ID`, `ALPACA_DATA_SECRET_KEY`. Acquire from the Alpaca sandbox dashboard (separate from the Broker OAuth credentials).

### D2. Schema sharing between backend & iOS → **(b) Hand-mirror with CI diff check**
Pydantic exports `app/ai/schema/v1.json` at build time; CI test compares iOS `enum Block` / `enum SSEEvent` variant names against it and fails on drift. v0's 3 block types + 8 event types are small enough that hand-maintaining is cheaper than picking and wiring a codegen tool, and Swift enums with associated values read more idiomatically than codegen output. Revisit at MVP scale (~12+ block types).

### D3. Where the AI module lives in `sevino-api` → **(a) `app/ai/` top-level**
Self-contained vertical, peer of `app/services/`, `app/routes/`. Contains runtime, prompts, tools, transport, observability, schema. Keeps the "swap orchestrator" exit hatch from architectural-decision-1 real (only `app/ai/runtime/` would change if we ever adopt LangGraph). Full layout in §5.

### D4. Langfuse SDK vs OpenTelemetry → **(a) Langfuse Python SDK directly**
`@observe` decorator + manual `langfuse.trace()` for nested spans. SDK has Anthropic-native helpers (auto-extracts thinking tokens, cache reads/writes, handles streaming spans) that OTel exporters lose. No other OTel consumer in the codebase — Sentry handles error/perf, structlog goes to Railway. Single-purpose OTel adoption is overhead with no payoff.

### D5. Markdown library on iOS → **(a) `swift-markdown-ui`**
Pure SwiftUI, full GFM, themeable via SwiftUI environment values (fits existing `SevinoGlass` patterns). Apple's built-in `AttributedString` + Markdown only handles inline formatting, not block elements (lists, code blocks, headings) which Claude emits regularly. One SPM dep, no transitive bloat. Add to `Sevino.xcodeproj` SPM dependencies.

### D6. Conversation creation — implicit vs explicit → **(a) Implicit on first turn**
`POST /v1/conversations/{id}/turns` accepts a client-generated UUID; endpoint creates the conversation row if missing (atomic upsert in the same short transaction as the user message insert). No `POST /v1/conversations` endpoint in v0. `GET /v1/conversations` for the recents list is post-v0.

### D7. Schema collision resolution → **(a) ALTER existing tables in place**
Drop `started_at`/`preview` from `conversations` (add `created_at`); drop `content`/`mcp_cards`/`tool_calls` from `messages` (add `content_blocks JSONB NOT NULL DEFAULT '[]'`). Safe because both tables are empty. `order_events.conversation_id` FK preserved. Single Alembic migration containing the ALTERs and the three new tables (`agent_turns`, `model_invocations`, `tool_executions`).

### D9. Default model for the main agent → **(a) Sonnet 4.6 main, Haiku 4.5 smoke**
`MODELS.MAIN = "claude-sonnet-4-6"` and `MODELS.SMOKE = "claude-haiku-4-5-20251001"` in `app/ai/models.py`. Sonnet 4.6 with extended thinking is strong enough for v0 scope (single tool, simple decisions); Opus 4.7 is overkill for "look up a stock price" and ~5× the cost. Make `ANTHROPIC_MODEL_MAIN` env-overridable so we can A/B in prod without redeploy.

### D10. Smoke harness CI gating → **(c) Path-filtered + force label**
GitHub Actions workflow runs the smoke harness when:
- The PR touches any file under `sevino-api/app/ai/**` or `sevino-api/tests/ai/**`, OR
- The PR has the label `run-ai-smoke` (force-run for cross-cutting changes that don't touch `app/ai/` but might break the AI flow — e.g., changes to `app/exceptions.py`, `app/middleware/logging.py`, `app/database.py`).

Plus a scheduled run on `main` push so we get a daily signal even when no AI PRs land. All gated on `RUN_AI_SMOKE` secret being present (CI is a no-op without the secret, so contributor forks don't fail spuriously).

### D11. Chat turn endpoint rate limit → **(a) `30/min/user`**
A real chat turn takes 5-30s — `30/min` allows ~15 concurrent turns in flight which is well past realistic UX. Slowapi storage is Redis, so the limit can be tuned with no redeploy. Codebase default `120/min` invites stuck-loop bugs to bill into the hundreds.

### D12. DB session pattern for the streaming chat endpoint → **(a) Session-per-write factory**
The chat turn endpoint does NOT use `Depends(get_db)`. New helper at `app/ai/runtime/db.py` returns an async context manager factory; each repository call inside the agent loop opens a fresh `AsyncSession`, commits, closes. This is a deliberate divergence from the rest of the codebase — load-bearing because (1) asyncpg + pgbouncer transaction-mode + a 60s held connection is asking for trouble, and (2) the spec's "no DB transaction across the streaming turn" rule is non-negotiable. **Flag in PR review** so future cleanup passes don't try to "normalize" it back.

---

## 4. Risks and unknowns

**R1. Anthropic streaming + extended thinking + tools is fiddly.**
Subsequent iterations require the prior assistant content (incl. thinking blocks with signatures) passed back verbatim. Anthropic returns 400s if signatures are stripped. *Mitigation:* the `model_invocations.response_content` JSONB is the source of truth for what to pass back on iteration N+1 — never reconstruct from intermediate state. Add an integration test that round-trips a tool-using turn and validates iteration 2's request payload contains the iteration-1 thinking signature.

**R2. asyncpg + long streaming responses can leak connections.**
The DB session dependency auto-commits at the END of the request. For a 60-second turn, that means the connection is held the whole time — not catastrophic, but contrary to the "short transactions only at write points" rule. *Mitigation:* the chat turn endpoint should NOT use `Depends(get_db)`. Instead, `Depends(get_db_factory)` returning an async context manager factory; the agent loop opens a fresh session per write, commits, closes. Pattern lives in `app/ai/runtime/db.py`. **This is a real pattern divergence from the rest of the codebase — flag in PR review.**

**R3. `sse-starlette` + slowapi compatibility.**
slowapi's middleware works at request level (verified — see `rate_limit.py` patterns), so the rate limit fires before the stream starts. But slowapi's `SlowAPIMiddleware` reads `response.status_code` after the handler returns, which for SSE means after the stream closes. This *should* be fine but worth verifying with a 10-second chat turn under load on a Railway preview before declaring Phase 1 done.

**R4. Cancellation timing on Anthropic stream.**
Anthropic's Python SDK 0.40+ supports `await stream.close()` to abort an in-flight stream; the server-side cancel is documented as "best effort". *Mitigation:* on disconnect, we close the stream AND mark the turn `cancelled`. We do NOT charge users for cancelled turns (don't count them against the rate limit) — needs a slowapi exemption when the turn ends `cancelled` within first 500ms. Defer if complex; record a TODO.

**R5. Idempotency key crashes between Redis-set and turn-end.**
If the API process dies between setting the `in_flight` key and the `try/finally` running, the key sits at `in_flight` for 2 minutes blocking retries. *Mitigation:* short TTL (2 min) is the backstop. Document the failure mode. Postgres-backed idempotency is the v1 fix.

**R6. Postgres JSONB volume.**
Spec estimates 60KB/turn × 10k turns/day = ~18GB/month. Supabase handles this fine but indexed JSONB queries get slow at 100GB+. *Mitigation:* `archived_at` column from day one (already in spec). Don't index inside JSONB columns yet. Build a `tool_executions_metadata` flat row with `started_at`, `latency_ms`, `tool_name`, `status` for fast queries — *defer this to MVP*; v0 just needs the JSONB.

**R7. Markdown rendering during stream.**
`text_delta` events arrive at ~50/sec. Re-parsing the entire markdown string on every delta is a perf footgun. *Mitigation:* swift-markdown-ui parses on string change but uses SwiftUI's diffing — should be OK for short messages. Watch for jank on long replies; if observed, debounce parser to ~30Hz (not per-delta).

**R8. iOS `URLSession.bytes(for:)` keepalive.**
On iOS 17+, `URLSession.bytes(for:)` does NOT auto-reconnect. If the OS suspends the app mid-stream, the stream errors out. *Mitigation:* v0 spec already says reconnect is post-v0. Just ensure the SSEClient surface allows future reconnect injection (the header provider pattern handles this — auth is fresh on every reconnect).

**R9. Existing `app/listeners/base_sse.py` is 418 LOC of SSE consumption code.**
Tempting to share with the SSE-emit code, but they're inverted concerns. *Recommendation:* **don't share**. Read `base_sse.py` for patterns (correlation IDs, structured logs, Sentry breadcrumbs) and apply them to the new emitter, but don't extract a base class.

**R10. Smoke harness cost on every PR.**
Real Claude calls × CI runs × Haiku rates = small but real bill. *Mitigation:* gate on `RUN_AI_SMOKE` secret, run on `main` push only (not every PR). Contributors can flip a label `run-ai-smoke` on a PR if they want it run on a feature branch. Document this in `tests/ai/smoke/README.md`.

---

## 5. Proposed directory layout

### `sevino-api/app/ai/` (new top-level module)

```
sevino-api/app/ai/
├── __init__.py
├── anthropic_client.py       # Singleton wrapper, exposed via app.state.anthropic
├── models.py                 # MODELS.SONNET, MODELS.HAIKU, etc. (string constants)
├── prompts/
│   ├── __init__.py           # load_prompt() → (text, hash)
│   └── sevino_v1.md          # the system prompt
├── blocks.py                 # TextBlock, StatusBlock, StockCardBlock, Block discriminated union
├── runtime/
│   ├── __init__.py
│   ├── loop.py               # run_agent_turn(...) — the agent loop
│   ├── caps.py               # HardCaps dataclass + cap checks
│   ├── cost.py               # cost_usd_micros(usage, model_id)
│   ├── errors.py             # ErrorCode enum + to_error_code mapper
│   └── db.py                 # session-per-write helper (NOT get_db)
├── tools/
│   ├── __init__.py
│   ├── base.py               # Tool ABC, ToolResult, ToolContext, ToolRegistry
│   └── get_stock_info.py     # The one v0 tool
├── transport/
│   ├── __init__.py
│   ├── events.py             # SSE event Pydantic models + serializer
│   ├── emitter.py            # SSEEmitter abstraction
│   └── idempotency.py        # Redis-backed idempotency middleware
├── observability/
│   ├── __init__.py
│   └── langfuse.py           # Langfuse singleton + span decorators
└── schema/
    └── v1.json               # Generated JSON schema, committed
```

Adjacent additions:

```
sevino-api/app/
├── routes/
│   └── conversations.py      # POST /v1/conversations/{id}/turns
├── repositories/
│   └── conversation.py       # ConversationRepository
├── models/
│   ├── conversation.py       # MODIFY: drop preview/started_at, add created_at
│   ├── message.py            # MODIFY: drop content/mcp_cards/tool_calls, add content_blocks
│   ├── agent_turn.py         # NEW
│   ├── model_invocation.py   # NEW
│   └── tool_execution.py     # NEW
├── services/
│   └── alpaca_market_data.py # NEW: separate from alpaca_broker.py
└── migrations/versions/
    └── <hash>_add_agent_runtime_tables.py  # NEW
```

Tests:

```
sevino-api/tests/
├── ai/
│   ├── unit/
│   │   ├── test_blocks.py
│   │   ├── test_caps.py
│   │   ├── test_cost.py
│   │   ├── test_idempotency.py
│   │   ├── test_emitter.py
│   │   └── test_loop.py             # agent loop with mocked Anthropic
│   ├── integration/
│   │   ├── test_chat_turn_endpoint.py  # full flow with mocked Anthropic + real DB
│   │   ├── test_idempotent_replay.py
│   │   ├── test_cancellation.py
│   │   └── test_conversation_repo.py
│   └── smoke/
│       ├── README.md                # how/when this runs
│       └── test_real_anthropic.py   # gated on RUN_AI_SMOKE
└── fixtures/
    └── ai/
        ├── sample_anthropic_responses.json
        └── sample_alpaca_market_data.json
```

### `sevino-app` chat layer

```
sevino-app/Sevino/Sevino/
├── Models/
│   ├── Chat/
│   │   ├── Message.swift           # struct Message + Role enum
│   │   ├── Block.swift             # enum Block: Codable, Identifiable
│   │   ├── SSEEvent.swift          # enum SSEEvent: Decodable
│   │   └── StockCardData.swift     # NEW (StockCardBlock payload — Bars, RangeOption, etc.)
│   └── (existing — unchanged)
├── Services/
│   ├── Chat/
│   │   ├── SSEClient.swift         # actor, URLSession.bytes-based
│   │   └── ChatService.swift       # MODIFY: replace placeholder with real send(turn:) -> AsyncStream
│   └── (existing — unchanged)
├── ViewModels/
│   ├── Chat/
│   │   ├── ConversationStore.swift # @Observable @MainActor — owns messages, applies events
│   │   └── (existing TickerMentionViewModel — unchanged)
│   └── Home/
│       └── HomeViewModel.swift     # MODIFY: hold a ConversationStore reference
└── Views/
    ├── Chat/
    │   ├── MessageListView.swift   # scrollable [Message] renderer
    │   └── Blocks/
    │       ├── TextBlockView.swift  # markdown via swift-markdown-ui
    │       ├── StatusPillView.swift
    │       └── StockCardView.swift  # Swift Charts line + range pills
    └── Home/
        └── HomeView.swift          # MODIFY: overlay MessageListView when conversation active
```

Tests:

```
sevino-app/Sevino/SevinoTests/
└── Chat/
    ├── SSEClientTests.swift        # parser, header provider, line buffer
    ├── ConversationStoreTests.swift
    ├── BlockDecodingTests.swift    # round-trip JSON → enum Block
    └── Mocks/
        └── MockSSEClient.swift     # already-imagined pattern
```

---

## 6. Linear project + epic structure

**Initiative:** `Sevino MVP Launch 🪐` (id `57a68cd2-…`, exists).

**Existing related projects to coordinate with (do NOT recreate):**
- `Conversation Persistence` (id `15976c8d-…`) — pre-existing project tracking the existing `conversations`/`messages` tables. AI v0 takes ownership of the schema migration (per D7). Project either rolls under AI v0 or gets closed/repurposed once the new schema lands.
- `Alpaca — Portfolio & Market Data` (id `ab45b6ca-…`) — natural home for the new `app/services/alpaca_market_data.py` client (the underlying Alpaca integration), although the *tool* wrapper goes in the AI project.
- `AI Radar (Data Layer)` (id `248b5bbe-…`) — pre-existing, uses different naming convention (no `AI —` prefix). Out of scope for v0 but the AI radar feature IS the proof of why v0's tool framework needs to support arbitrary tools cleanly. Worth a coordination convo.
- `API Infrastructure`, `Sentry Setup`, `Frontend Infrastructure` — existing. Touch points for CI scaffolding (we'll add `.github/workflows/ci.yml`), observability (Langfuse joins Sentry), and iOS new files.

**Proposed new projects (to create):**

> Linear hierarchy is **Initiatives → Projects → Issues**. There is no native "epic" entity. v0 maps cleanly to **three projects, one per phase** — each project is a coherent demoable milestone with its own proof-of-life. Splitting any finer creates administrative overhead without value at this size; merging back to two re-couples the risks the 3-phase split was designed to separate.
>
> Within each project, issues are **flat — no parent-issue hierarchy**. Linear's native labels handle the conceptual grouping; engineers work straight from the project's issue list. The visual grouping in this doc (by `area:*` label) is for human readability while planning. Promote a grouping to a real parent issue later only if the team finds shared design context that doesn't fit in the project description or in a single design-spike issue.
>
> **Suggested label taxonomy (create once at the workspace level):**
> - `area:runtime` — agent loop, Anthropic plumbing, system prompt, caps, error taxonomy
> - `area:persistence` — DB models, migrations, repositories
> - `area:transport` — SSE event protocol, chat turn endpoint, emitter
> - `area:safety` — idempotency, cancellation
> - `area:observability` — Langfuse, traces, cost
> - `area:tools` — tool framework, individual tools (`get_stock_info`)
> - `area:alpaca-data` — Alpaca Market Data client (separate from `services/alpaca_broker.py`)
> - `area:ios` — anything in `sevino-app/`
> - `area:schema` — block / event Pydantic models, schema-sync artifact
> - `area:ci` — GitHub Actions, smoke harness

**Conventions used below:**
- Issue IDs (`A1.1`, `B2.3`, etc.) are local to this doc for cross-referencing dependencies. Linear will assign its own `SEV-XXX` IDs at creation time.
- Each issue is one PR.
- Visual grouping headings (`#### Issues — area:runtime`) are doc-only. In Linear, all issues are flat siblings; tag them with the indicated label(s) and the visual grouping reproduces itself via filter.
- Estimates: **S** = ≤4h focused work, **M** = ½–1 day, **L** = 1–2 days.
- "Files" lists key paths the issue creates or modifies — not exhaustive.

---

### Project A: `AI — Foundation`
**Purpose:** Phase 1. Make a single full-payload Claude turn work end-to-end with full audit. No SSE, no idempotency, no tools.

**Demo when done:** `curl -d '{"message":"hi","idempotency_key":"x"}' /v1/conversations/$ID/turns` returns a JSON response after a few seconds; `agent_turns` + `model_invocations` rows present with full thinking signatures; Langfuse trace with cost.

#### Issues — `area:runtime`
The Anthropic plumbing, agent loop, and the things that need to wrap it (caps, errors, caching, thinking).

**A1.1 — Add Anthropic SDK + singleton client**
- Add `anthropic>=0.40.0` to `pyproject.toml`. Create `app/ai/anthropic_client.py` mirroring `services/alpaca_broker.py` shape: instantiated in `app/lifecycle.py`, attached to `app.state.anthropic`, accessed via `Depends(get_anthropic)`.
- **Acceptance:** `AsyncAnthropic` instance on `app.state.anthropic`; `await client.aclose()` in shutdown; new env var `ANTHROPIC_API_KEY` in `.env.example` + `app/config.py` Settings.
- **Files:** `pyproject.toml`, `app/ai/anthropic_client.py`, `app/lifecycle.py`, `app/config.py`, `.env.example`
- **Depends on:** —
- **Estimate:** S

**A1.2 — Define model constants**
- New `app/ai/models.py` with `MODELS.MAIN = "claude-sonnet-4-6"`, `MODELS.SMOKE = "claude-haiku-4-5-20251001"`. Make `MAIN` env-overridable via `ANTHROPIC_MODEL_MAIN` (per D9).
- **Acceptance:** Constants accessible as `from app.ai.models import MODELS`; env override works; documented in `.env.example`.
- **Files:** `app/ai/models.py`, `app/config.py`, `.env.example`
- **Depends on:** —
- **Estimate:** S

**A1.3 — Versioned system prompt + hash loader**
- New `app/ai/prompts/sevino_v1.md` with the v0 system prompt (placeholder content for now — copy edit in a later PR). Loader in `app/ai/prompts/__init__.py`: reads file at import-time, computes `hashlib.sha256().hexdigest()`, exposes `(text, hash)` tuple.
- **Acceptance:** Importing `from app.ai.prompts import SYSTEM_PROMPT_V1` returns text + hash; hash is stable across restarts; unit test asserts hash changes when file changes.
- **Files:** `app/ai/prompts/__init__.py`, `app/ai/prompts/sevino_v1.md`, `tests/ai/unit/test_prompts.py`
- **Depends on:** —
- **Estimate:** S

**A1.4 — Hard caps dataclass + cap-check helpers**
- New `app/ai/runtime/caps.py`. `HardCaps` frozen dataclass with `max_iterations=10, max_tool_calls=20, max_wall_clock_s=60, max_output_tokens=2048`. Helper `check_caps(state) -> CapBreach | None`.
- **Acceptance:** Each cap maps to a distinct `terminal_state` value (`iteration_limit`, `tool_call_limit`, `timeout`, `output_token_limit`); unit tests cover each breach.
- **Files:** `app/ai/runtime/caps.py`, `tests/ai/unit/test_caps.py`
- **Depends on:** —
- **Estimate:** S

**A1.5 — Error taxonomy enum + exception mapper**
- New `app/ai/runtime/errors.py`. `ErrorCode` enum (10 values per spec). Mapping function `to_error_code(exc: Exception) -> ErrorCode`. Recognises `anthropic.RateLimitError`, `anthropic.APIStatusError`, `asyncio.CancelledError`, `asyncio.TimeoutError`, `pydantic.ValidationError`, generic fallthrough.
- **Acceptance:** Unit test asserts each known exception type maps to the right code; unknown exceptions map to `internal_error`.
- **Files:** `app/ai/runtime/errors.py`, `tests/ai/unit/test_errors.py`
- **Depends on:** —
- **Estimate:** S

**A1.6 — Agent loop core (`run_agent_turn`)**
- New `app/ai/runtime/loop.py`. Pure async function `run_agent_turn(*, user_id, conversation_id, user_message, db_factory, tool_registry, system_prompt, model_config, hard_caps) -> AgentTurnResult`. No FastAPI imports. v0 has no tools, so the loop runs exactly one Anthropic call. Each iteration: build messages array, call Anthropic, persist `model_invocation` row in its own short transaction (via `db_factory`), append assistant content. Stop on `stop_reason == "end_turn"` or any cap breach.
- **Acceptance:** Returns `AgentTurnResult(terminal_state, assistant_message_blocks, total_cost_usd_micros, iterations_count)`; `model_invocations` rows persisted per-iteration with full request/response JSON; integration test with mocked Anthropic asserts persistence shape.
- **Files:** `app/ai/runtime/loop.py`, `app/ai/runtime/db.py` (the session-per-write factory per D12), `app/ai/runtime/types.py`, `tests/ai/unit/test_loop.py`, `tests/ai/integration/test_loop_persistence.py`
- **Depends on:** A1.1, A1.2, A1.3, A1.4, A1.5, A2.4
- **Estimate:** L

**A1.7 — Extended thinking + signature roundtripping**
- Pass `thinking={"type": "enabled", "budget_tokens": 1024}` on every Anthropic call. On iteration N+1, pass prior assistant content (incl. thinking blocks **with signatures**) back verbatim. Track `total_thinking_tokens` separately on `agent_turns`.
- **Acceptance:** Integration test forces a multi-iteration turn (mocked tool call) and verifies iteration 2's request payload contains iteration 1's thinking signature; `model_invocations.response_content` is the source of truth that gets passed back (never reconstructed).
- **Files:** `app/ai/runtime/loop.py` (extension), `tests/ai/integration/test_thinking_roundtrip.py`
- **Depends on:** A1.6
- **Estimate:** M

**A1.8 — Prompt caching markers**
- Mark system prompt block + tool definitions array (when present — empty in Phase 1) with `cache_control: {"type": "ephemeral"}` on the Anthropic request. One-line change per cacheable block.
- **Acceptance:** Integration test asserts cache markers present in `model_invocations.request_system` JSONB; smoke harness shows `cache_read_input_tokens > 0` on the second turn.
- **Files:** `app/ai/runtime/loop.py` (extension)
- **Depends on:** A1.6
- **Estimate:** S

**A1.9 — Temporary JSON-mode chat turn endpoint**
- New `app/routes/conversations.py` with `POST /v1/conversations/{id}/turns` returning `application/json`. Body `{message: str, idempotency_key: str}` — `idempotency_key` is accepted but ignored in Phase 1 (just shape-stable for clients). Calls `run_agent_turn(...)`. Behind `Depends(get_current_user)`. Slowapi limit `30/min/user` (per D11). Endpoint URL is the same one Phase 2 will flip to SSE; only the response transport changes.
- **Acceptance:** `curl` returns the assistant message blocks as JSON; `conversations` row created on first turn (per D6); `agent_turns` row populated; CI integration test asserts 200 + body shape with mocked Anthropic.
- **Files:** `app/routes/conversations.py`, `app/main.py` (router include), `app/schemas/conversations.py`, `tests/ai/integration/test_chat_endpoint_json.py`
- **Depends on:** A1.6
- **Estimate:** M

#### Issues — `area:persistence`
The Alembic migration and the data-access layer.

**A2.1 — Alembic migration: agent runtime tables + ALTER existing**
- One migration: ALTER `conversations` (drop `started_at`/`preview`, add `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`); ALTER `messages` (drop `content`/`mcp_cards`/`tool_calls`, add `content_blocks JSONB NOT NULL DEFAULT '[]'`); CREATE `agent_turns`, `model_invocations`, `tool_executions` per spec (incl. `agent_role` defaulting to `"main"` and `parent_tool_execution_id` self-FK from day one). Use TEXT for enum columns (matches existing `plaid_items.status` convention — no `PgEnum`).
- **Acceptance:** `make migrate` applies cleanly to a fresh local Supabase; `alembic heads` shows one head; `order_events.conversation_id` FK still valid; `make test` green; rollback (`alembic downgrade -1`) does not error.
- **Files:** `migrations/versions/<hash>_add_agent_runtime_tables.py`, `migrations/env.py` (add new model imports)
- **Depends on:** A2.2, A2.3 (model files must exist for autogenerate to detect — but autogenerate is reviewed not trusted; you may write the migration by hand)
- **Estimate:** M

**A2.2 — New ORM models (`agent_turn`, `model_invocation`, `tool_execution`)**
- Three new files in `app/models/` inheriting `Base`, `UUIDPrimaryKeyMixin`, `TimestampMixin`. Full schema per spec. Self-FK on `tool_executions.parent_tool_execution_id`. JSONB columns use the existing `Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)` pattern.
- **Acceptance:** Models import without circular-import errors; `models/__init__.py` re-exports; relationship navigation (`turn.invocations`, `invocation.tool_executions`) works in unit test.
- **Files:** `app/models/agent_turn.py`, `app/models/model_invocation.py`, `app/models/tool_execution.py`, `app/models/__init__.py`
- **Depends on:** —
- **Estimate:** M

**A2.3 — Modify existing `conversation` and `message` models**
- Update `app/models/conversation.py` to drop `preview`/`started_at`, add `created_at`. Update `app/models/message.py` to drop `content`/`mcp_cards`/`tool_calls`, add `content_blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")`. Verify `order_events.conversation_id` relationship still resolves.
- **Acceptance:** Models match the migration in A2.1; `make test` green (no places in the codebase reference removed columns — verified by grep).
- **Files:** `app/models/conversation.py`, `app/models/message.py`
- **Depends on:** —
- **Estimate:** S

**A2.4 — `ConversationRepository` implementation**
- New `app/repositories/conversation.py`. `@staticmethod` methods only, `db: AsyncSession` first arg (matches existing repository convention): `create_conversation`, `load_history`, `append_user_message`, `append_assistant_message_with_blocks`, `start_agent_turn`, `complete_agent_turn`, `record_model_invocation`, `record_tool_execution`. Each method does its own write + flush; transaction boundaries are owned by the caller (the agent loop's `db_factory`, not `get_db`).
- **Acceptance:** Integration test against real local Postgres asserts: insert→read→update flows for each method; `record_model_invocation` writes immediately (not batched at end of turn); concurrent calls don't deadlock.
- **Files:** `app/repositories/conversation.py`, `tests/ai/integration/test_conversation_repo.py`
- **Depends on:** A2.2, A2.3
- **Estimate:** M

**A2.5 — Cost calculator**
- New `app/ai/runtime/cost.py`. Function `cost_usd_micros(usage: anthropic.types.Usage, model_id: str) -> int`. Rate table per model (input, output, cache read, cache write, thinking are billed at output rate). Returns integer microUSD.
- **Acceptance:** Unit tests: known usage → known cost (within rounding); unknown model_id raises with a clear error.
- **Files:** `app/ai/runtime/cost.py`, `tests/ai/unit/test_cost.py`
- **Depends on:** —
- **Estimate:** S

#### Issues — `area:observability`
Langfuse Cloud, traces, cost.

**A3.1 — Add Langfuse dependency + singleton init**
- Add `langfuse` to `pyproject.toml`. Singleton `Langfuse` client in `app/ai/observability/langfuse.py`. Initialised in `app/lifecycle.py` (no-op if `LANGFUSE_PUBLIC_KEY` is empty — for local dev without an account). `await client.flush()` in shutdown. New env vars `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (defaults to `https://cloud.langfuse.com`).
- **Acceptance:** `app.state.langfuse` is configured Langfuse instance (or a no-op stub if creds missing); env vars documented; smoke test asserts that a manual `client.trace(...)` call produces a trace ID without erroring.
- **Files:** `app/ai/observability/langfuse.py`, `app/lifecycle.py`, `app/config.py`, `.env.example`
- **Depends on:** —
- **Estimate:** S

**A3.2 — Wrap Anthropic calls + tool executions in spans**
- In the agent loop, wrap each Anthropic call in a Langfuse span via `@observe` decorator or manual `langfuse.trace()`. Tags: `user_id`, `conversation_id`, `turn_id`, `prompt_hash`, `environment`, `model_id`. (Tool spans land in Project C when tools exist.)
- **Acceptance:** End-to-end test with real Langfuse Cloud (env-flagged) shows a trace per turn with all expected tags; `agent_turn.id` appears as the trace ID for cross-referencing.
- **Files:** `app/ai/runtime/loop.py` (extension), `app/ai/observability/langfuse.py`
- **Depends on:** A3.1, A1.6
- **Estimate:** M

**A3.3 — Cost + token usage attached to traces**
- After each Anthropic call, attach usage + cost to the Langfuse span via `span.update(usage={...}, cost={...})`. Use the `cost_usd_micros` function from A2.5.
- **Acceptance:** Langfuse Cloud trace shows USD cost per turn; usage breakdown (input, output, cache read, cache write, thinking) visible.
- **Files:** `app/ai/runtime/loop.py` (extension)
- **Depends on:** A3.2, A2.5
- **Estimate:** S

#### Issues — `area:ci`
Scaffold CI.

**A4.3 — GitHub Actions CI scaffold**
- New `.github/workflows/ci.yml` running `uv sync` + `make test` on every PR. Postgres + Redis services in the workflow. **Smoke harness deferred to Project B.** No Anthropic-related secrets needed at this stage.
- **Acceptance:** CI green on a no-op PR; CI red on a failing test PR (verify by intentionally breaking a test in a draft PR); workflow takes <5 min on average.
- **Files:** `.github/workflows/ci.yml`
- **Depends on:** —
- **Estimate:** M

#### Project A — Parallelization & critical path

```
Wave 1 (start day 1, all independent):
  A1.1 (SEV-460) Anthropic SDK
  A1.2 (SEV-461) Model constants
  A1.3 (SEV-462) System prompt + hash
  A1.4 (SEV-463) Hard caps
  A1.5 (SEV-464) Error taxonomy
  A2.2 (SEV-470) New ORM models
  A2.3 (SEV-471) Modified existing models
  A2.5 (SEV-473) Cost calculator
  A3.1 (SEV-474) Langfuse singleton
  A4.3 (SEV-479) GitHub Actions

Wave 2 (after Wave 1 ships):
  A2.1 (SEV-469) Alembic migration            ← depends on A2.2, A2.3
  A2.4 (SEV-472) ConversationRepository       ← depends on A2.2, A2.3

Wave 3 (after Wave 2):
  A1.6 (SEV-465) Agent loop core              ← depends on A1.1-1.5, A2.4
                                                  *** CRITICAL PATH ***

Wave 4 (after A1.6):
  A1.7 (SEV-466) Extended thinking
  A1.8 (SEV-467) Prompt caching                These three can ship in parallel
  A1.9 (SEV-468) JSON endpoint                 once A1.6 lands.
  A3.2 (SEV-475) Langfuse spans

Wave 5 (after Wave 4):
  A3.3 (SEV-476) Cost on traces                ← A3.2 + A2.5
```

**Critical path:** `A2.2/A2.3 (SEV-470/471) → A2.4 (SEV-472) → A1.6 (SEV-465) → A1.9 (SEV-468) → demo`. Roughly 1 day per wave with one engineer; with two engineers in parallel on Wave 1, the critical path drives the timeline (~3 days). With 3+ engineers there's diminishing return — A1.6 is one PR.

**For two engineers:**
- **E1 (sequential / critical path):** A2.2 (SEV-470) → A2.4 (SEV-472) → A1.6 (SEV-465) → A1.9 (SEV-468)
- **E2 (parallel / supporting):** A1.1 (SEV-460), A1.2 (SEV-461), A1.3 (SEV-462), A1.4 (SEV-463), A1.5 (SEV-464) (Wave 1) → A2.1 (SEV-469), A2.3 (SEV-471) (Wave 2) → A1.7 (SEV-466), A1.8 (SEV-467), A3.1 (SEV-474) → A3.2 (SEV-475), A3.3 (SEV-476) → A4.3 (SEV-479)

---

### Project B: `AI — Streaming & Safety`
**Purpose:** Phase 2. Flip the JSON endpoint to SSE. Add idempotency. Add cancellation. Same response content, real chat-turn semantics.

**Demo when done:** `curl -N` streams text deltas live; same idempotency key replays the persisted message; Ctrl-C mid-stream cancels server-side and persists partial assistant message.

#### Issues — `area:schema`
Pydantic discriminated unions for what comes out of the agent.

**B1.1 — Block discriminated union (TextBlock + StatusBlock)**
- New `app/ai/blocks.py`. Pydantic `TextBlock(type="text", block_id, text)` and `StatusBlock(type="status", block_id, label, state: Literal["active","complete","failed"])`. `Block = Annotated[TextBlock | StatusBlock, Field(discriminator="type")]`. StockCardBlock is added in C1.3.
- **Acceptance:** `Block.model_validate({"type": "text", ...})` produces correct subclass; round-trip JSON serialisation preserves variant; `messages.content_blocks` JSONB accepts a list of Block dicts.
- **Files:** `app/ai/blocks.py`, `tests/ai/unit/test_blocks.py`
- **Depends on:** —
- **Estimate:** S

**B1.2 — SSE event types**
- New `app/ai/transport/events.py`. Pydantic models for `TurnStarted, Status, BlockStart, TextDelta, BlockData, BlockEnd, TurnCompleted, Error` (8 events per spec). Each event has a stable `id: str` field (ULID — install `python-ulid` if not already there). Wire-format serializer producing `id: <ulid>\nevent: <type>\ndata: <json>\n\n` strings.
- **Acceptance:** Each event serialises to the correct `event:` name; `id:` field present on every event; round-trip parse produces equivalent model.
- **Files:** `app/ai/transport/events.py`, `tests/ai/unit/test_events.py`, `pyproject.toml` (`python-ulid` if needed)
- **Depends on:** —
- **Estimate:** M

#### Issues — `area:transport`
The endpoint flips from JSON to SSE.

**B2.1 — Add `sse-starlette` dependency**
- Add `sse-starlette` to `pyproject.toml`. No code change yet — separate ticket so the dep change is reviewable on its own.
- **Acceptance:** `uv sync` succeeds; `from sse_starlette.sse import EventSourceResponse` imports.
- **Files:** `pyproject.toml`, `uv.lock`
- **Depends on:** —
- **Estimate:** S

**B2.2 — `SSEEmitter` abstraction**
- New `app/ai/transport/emitter.py`. `class SSEEmitter` holding an `asyncio.Queue[Event]`. Methods: `await emit(event: Event)`, `iter_events() -> AsyncIterator[Event]`, `close()`. Endpoint wires emitter's iterator to `EventSourceResponse`.
- **Acceptance:** Unit test: spawn a coroutine that emits 3 events, consume via `async for` — receives all 3 in order; `close()` ends the iterator cleanly.
- **Files:** `app/ai/transport/emitter.py`, `tests/ai/unit/test_emitter.py`
- **Depends on:** B1.2
- **Estimate:** M

**B2.3 — Flip chat turn endpoint to SSE**
- Modify `app/routes/conversations.py` to return `EventSourceResponse` instead of JSON. Endpoint creates an `SSEEmitter`, spawns the agent loop in a background task with the emitter, and yields events from the emitter to the response. **The endpoint URL and request shape do NOT change** — only the response transport. Existing JWT + slowapi work unchanged.
- **Acceptance:** `curl -N` to the endpoint shows event stream with `turn_started`, `text_delta` chunks, `turn_completed`; integration test parses the SSE stream and asserts event sequence.
- **Files:** `app/routes/conversations.py` (modified), `tests/ai/integration/test_chat_endpoint_sse.py` (replaces `test_chat_endpoint_json.py`)
- **Depends on:** B2.1, B2.2, B1.2
- **Estimate:** M

**B2.4 — Wire agent loop to emit events**
- Modify `app/ai/runtime/loop.py` to accept an `SSEEmitter` parameter. Emit `turn_started` at the start; emit `block_start`/`text_delta`/`block_end` as Anthropic streams text; emit `turn_completed` with usage on success; emit `error` on cap breach or exception. Persist completed blocks to `messages.content_blocks` at end of turn.
- **Acceptance:** Integration test with mocked Anthropic streaming asserts the emitted event sequence matches the model output; `messages.content_blocks` row populated after success.
- **Files:** `app/ai/runtime/loop.py` (modified), `tests/ai/integration/test_loop_emits_events.py`
- **Depends on:** B2.3, B1.1, B2.2
- **Estimate:** L

#### Issues — `area:safety`

**B3.1 — Redis idempotency helpers**
- New `app/ai/transport/idempotency.py`. Helper module of plain async functions (`claim_idempotency`, `mark_complete`, `mark_failed`) called directly by the chat-turn route — *not* a Starlette `BaseHTTPMiddleware` and not a single FastAPI dependency, because the route needs surgical control over the `claim → mark_complete` / `mark_failed` boundaries that wrap `run_agent_turn`. State machine: not present → set `{status: "in_flight", turn_id, started_at}` 2-min TTL; complete → return marker for replay; in_flight → 409. `try/finally` in the endpoint marks `failed` on crash.
- **Acceptance:** Unit test (with fakeredis): two parallel requests with same key — first runs, second 409s. After first completes, third request with same key returns the complete marker. Crashed `try/finally` correctly transitions in_flight → failed within the TTL window.
- **Files:** `app/ai/transport/idempotency.py`, `tests/ai/unit/test_idempotency.py`
- **Depends on:** —
- **Estimate:** L

**B3.2 — Idempotent replay logic**
- When idempotency middleware reports `complete`, fetch the persisted assistant message via `ConversationRepository.load_assistant_message_for_turn(...)` and re-emit as a single SSE stream (`turn_started` → blocks → `turn_completed`) without invoking Anthropic.
- **Acceptance:** Integration test: send same key twice; second response matches the first byte-for-byte (modulo `id:` field which can be regenerated); `model_invocations` count stays at 1.
- **Files:** `app/routes/conversations.py` (extension), `app/repositories/conversation.py` (new method), `tests/ai/integration/test_idempotent_replay.py`
- **Depends on:** B3.1, B2.3, B2.4
- **Estimate:** M

**B3.3 — Cancellation: disconnect polling**
- Modify `app/ai/runtime/loop.py` to accept a `disconnect_check: Callable[[], Awaitable[bool]]` parameter. Check at every iteration boundary AND inside the streaming callback (every N text deltas). On `True`, raise `asyncio.CancelledError` from inside the loop, which propagates to the `try/finally`. The endpoint passes `request.is_disconnected` as the check.
- **Acceptance:** Integration test: client disconnects after 200ms; agent loop raises `CancelledError` within 1s; `agent_turns.terminal_state = 'cancelled'`.
- **Files:** `app/ai/runtime/loop.py` (extension), `app/routes/conversations.py` (extension)
- **Depends on:** A1.6, B2.3
- **Estimate:** M

**B3.4 — Cancellation: stream close + partial persistence**
- On cancellation, call `await stream.close()` on the in-flight Anthropic stream. Persist whatever blocks completed to `messages.content_blocks` before the `agent_turn` row updates with `terminal_state='cancelled'`.
- **Acceptance:** Integration test: cancel mid-text-delta; `messages.content_blocks` contains the partial text block; `agent_turns.cancellation_reason` is populated.
- **Files:** `app/ai/runtime/loop.py` (extension), `tests/ai/integration/test_cancellation_partial.py`
- **Depends on:** B3.3, A2.4
- **Estimate:** M

#### Issues — `area:ci` (smoke harness, first two cases)

**B4.1 — pytest smoke harness skeleton**
- New `tests/ai/smoke/conftest.py` and `tests/ai/smoke/README.md`. Smoke fixture spins up a local server + DB, calls the endpoint via real HTTP, parses SSE stream. Gated on `RUN_AI_SMOKE=1` env var; default-skipped otherwise.
- **Acceptance:** `RUN_AI_SMOKE=1 uv run pytest tests/ai/smoke -v` runs; default `make test` skips the directory.
- **Files:** `tests/ai/smoke/conftest.py`, `tests/ai/smoke/README.md`
- **Depends on:** A4.3
- **Estimate:** M

**B4.2 — Smoke case: `"hello"` turn**
- New `tests/ai/smoke/test_hello.py`. Sends `"say hello"` to the endpoint via real Anthropic (Haiku), asserts response stream completes with `turn_completed` and at least one text delta, asserts cost > 0 in `agent_turns`.
- **Acceptance:** Test passes against real Anthropic Haiku within 10s; cost recorded.
- **Files:** `tests/ai/smoke/test_hello.py`
- **Depends on:** B4.1, B2.4
- **Estimate:** S

**B4.3 — Smoke case: iteration cap breach**
- New `tests/ai/smoke/test_iteration_cap.py`. Crafts a prompt that would force Claude into a tool-call loop if a fake tool were available; with no tools registered (Phase 2 has no real tools yet), this case will use `max_iterations=2` override + a prompt designed to make Claude want tools. Asserts terminal state is `iteration_limit` and `error` event emitted with the right code.
- **Acceptance:** Test passes; surfaces the cap mechanism end-to-end.
- **Files:** `tests/ai/smoke/test_iteration_cap.py`
- **Depends on:** B4.1, B2.4
- **Estimate:** M

**B4.4 — CI workflow update for smoke harness**
- Modify `.github/workflows/ci.yml` to add a new job `smoke-ai`: runs when (a) PR touches `sevino-api/app/ai/**` or `sevino-api/tests/ai/**`, OR (b) PR has label `run-ai-smoke`, OR (c) push to `main`. Sets `RUN_AI_SMOKE=1`. Requires `ANTHROPIC_API_KEY` GitHub Actions secret.
- **Acceptance:** Trigger conditions verified manually (push a test PR touching `app/ai/`); secret-less PRs from forks don't fail spuriously.
- **Files:** `.github/workflows/ci.yml` (modified)
- **Depends on:** B4.2, B4.3
- **Estimate:** M

#### Project B — Parallelization & critical path

```
Wave 1 (start as soon as Project A merges; all independent):
  B1.1 (SEV-480) Block schema (TextBlock + StatusBlock)
  B1.2 (SEV-481) SSE event types
  B2.1 (SEV-482) Add sse-starlette dep
  B3.1 (SEV-486) Redis idempotency middleware

Wave 2 (after Wave 1):
  B2.2 (SEV-483) SSEEmitter                   ← B1.2

Wave 3 (after Wave 2):
  B2.3 (SEV-484) Flip endpoint to SSE         ← B2.1, B2.2, B1.2
  B4.1 (SEV-490) Smoke harness skeleton       (parallel — only depends on A4.3)

Wave 4 (after Wave 3):
  B2.4 (SEV-485) Wire loop to emit events     ← B2.3, B1.1, B2.2
                                                  *** CRITICAL PATH ***
  B3.2 (SEV-487) Idempotent replay            ← B3.1, B2.3, B2.4 (so really Wave 5)

Wave 5 (after B2.4):
  B3.3 (SEV-488) Cancellation: disconnect polling   ← B2.3, A1.6
  B3.4 (SEV-489) Cancellation: stream close + partial   ← B3.3
  B4.2 (SEV-491) Smoke: hello                       ← B2.4
  B4.3 (SEV-492) Smoke: iteration cap                ← B2.4

Wave 6:
  B4.4 (SEV-493) CI workflow update           ← B4.2, B4.3
```

**Critical path:** `B1.2 (SEV-481) → B2.2 (SEV-483) → B2.3 (SEV-484) → B2.4 (SEV-485)`. Plus B3.3 (SEV-488) → B3.4 (SEV-489) happens after the critical path. ~3 days end-to-end.

**For two engineers:**
- **E1 (critical path):** B1.2 (SEV-481) → B2.2 (SEV-483) → B2.3 (SEV-484) → B2.4 (SEV-485) → B3.3 (SEV-488) → B3.4 (SEV-489)
- **E2 (supporting):** B1.1 (SEV-480), B2.1 (SEV-482), B3.1 (SEV-486) (Wave 1) → B4.1 (SEV-490) → B3.2 (SEV-487) → B4.2 (SEV-491), B4.3 (SEV-492) → B4.4 (SEV-493)

---

### Project C: `AI — Tools & Chat Surface`
**Purpose:** Phase 3. Real tool, real block, real iOS chat. Closes the proof-of-life demo.

**Demo when done:** iOS sends "how is AMD doing", sees status pill + streaming text + live `StockCardBlock`. Cancellation works from iOS. Same idempotency key replays.

#### Issues — `area:tools` (framework)

**C1.1 — `Tool` ABC, `ToolResult`, `ToolContext`, `ToolRegistry`**
- New `app/ai/tools/base.py`. `Tool` ABC with `name: str`, `description: str`, `Input: type[BaseModel]`, `async execute(input: Input, ctx: ToolContext) -> ToolResult`. `ToolResult(model_payload: dict, ui_block: Block | None, internal_trace: dict | None)`. `ToolContext(user_id, db_factory, sse_emitter, http_clients, parent_emitter)`. `ToolRegistry` class with `register(tool)`, `get(name) -> Tool`, `to_anthropic_spec() -> list[dict]` (builds the tool definitions array Claude expects, with `cache_control` markers per A1.8).
- **Acceptance:** Unit test: register a fake tool, retrieve via registry, `to_anthropic_spec()` produces the right shape; `ToolResult` round-trips JSON.
- **Files:** `app/ai/tools/base.py`, `app/ai/tools/__init__.py`, `tests/ai/unit/test_tool_framework.py`
- **Depends on:** —
- **Estimate:** L

**C1.2 — Wire `ToolContext` into agent loop**
- Modify `app/ai/runtime/loop.py`: when Claude returns `stop_reason == "tool_use"`, look up tool by name in registry, validate input via `tool.Input.model_validate(...)`, call `await tool.execute(input, ctx)`, persist `tool_executions` row (with `internal_trace`, `ui_blocks_emitted`, `upstream_api_calls`, status), append tool result to messages, continue loop. Emit `block_start`/`block_data`/`block_end` for any UI block produced.
- **Acceptance:** Integration test with a fake echo tool: agent calls tool, tool result roundtrips, `tool_executions` row persisted with full trace, follow-up Anthropic call sees the tool result.
- **Files:** `app/ai/runtime/loop.py` (extension), `app/repositories/conversation.py` (extension), `tests/ai/integration/test_loop_tool_use.py`
- **Depends on:** C1.1, A1.6 (already present)
- **Estimate:** L

**C1.3 — `StockCardBlock` schema added to discriminated union**
- Extend `app/ai/blocks.py` with `StockCardBlock` (type="stock_card") matching the design: `symbol, company_name, logo_url, price, change_abs, change_pct, color_state, bars: list[Bar], range: str, range_options: list[str]`. Update the `Block = Annotated[...]` union.
- **Acceptance:** Block round-trips JSON; CI diff check (C5.2) catches if iOS doesn't get updated; integration with `messages.content_blocks` storage.
- **Files:** `app/ai/blocks.py` (extension), `tests/ai/unit/test_blocks.py` (extension)
- **Depends on:** B1.1
- **Estimate:** S

**C1.4 — Wire tool execution → SSE block events**
- When a tool's `execute()` returns a `ui_block`, the agent loop emits `block_start`/`block_data`/`block_end` for it. For `StockCardBlock`, the tool may emit incrementally (price arrives first, bars arrive later) by streaming `block_data` patches; the framework supports this via the emitter on `ToolContext`.
- **Acceptance:** Integration test with a fake tool that emits 3 incremental `block_data` patches: SSE stream contains the patches in order, final `messages.content_blocks` reflects the merged final state.
- **Files:** `app/ai/runtime/loop.py` (extension), `tests/ai/integration/test_block_streaming.py`
- **Depends on:** C1.2, C1.3, B2.4
- **Estimate:** M

#### Issues — `area:tools`, `area:alpaca-data` (`get_stock_info` & client)

**C2.1 — Acquire Alpaca Market Data sandbox creds + add env vars**
- Action item: generate `ALPACA_DATA_API_KEY_ID` + `ALPACA_DATA_SECRET_KEY` from Alpaca paper dashboard. Add to `.env.example`, `app/config.py` Settings (with `Optional` so existing dev environments don't break). Add `alpaca_market_data_base_url` computed property (sandbox vs prod, like the broker URL pattern).
- **Acceptance:** Settings loads with the new keys; computed URL property returns `https://data.sandbox.alpaca.markets` in dev/staging.
- **Files:** `.env.example`, `app/config.py`
- **Depends on:** —
- **Estimate:** S

**C2.2 — `AlpacaMarketDataService` HTTP client**
- New `app/services/alpaca_market_data.py`. Mirrors `services/alpaca_broker.py` shape (singleton `httpx.AsyncClient`, `close()` method, structured logging on errors). Auth: `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY` headers (NOT OAuth — different auth model than Broker API). Methods: `async get_latest_quote(symbol: str) -> dict`, `async get_bars(symbol: str, timeframe: str, start: datetime, end: datetime) -> dict`. New exception types `AlpacaMarketDataError`, `AlpacaMarketDataUnavailableError` mirroring broker exceptions.
- **Acceptance:** Integration test against real sandbox: `get_latest_quote("AAPL")` returns a quote object; error handling for invalid symbol surfaces `AlpacaMarketDataError`; transport errors surface `AlpacaMarketDataUnavailableError`.
- **Files:** `app/services/alpaca_market_data.py`, `app/exceptions.py` (register new exception handlers), `tests/integration/test_alpaca_market_data.py`
- **Depends on:** C2.1
- **Estimate:** L

**C2.3 — Lifecycle integration**
- Initialise `AlpacaMarketDataService` in `app/lifecycle.py`, attach to `app.state.alpaca_market_data`. New `Depends(get_alpaca_market_data)` helper. Close in shutdown.
- **Acceptance:** App boots without errors; `app.state.alpaca_market_data` is populated; shutdown closes the http client cleanly.
- **Files:** `app/lifecycle.py` (extension), `app/dependencies.py` or inline in route file
- **Depends on:** C2.2
- **Estimate:** S

**C2.4 — `get_stock_info` tool implementation**
- New `app/ai/tools/get_stock_info.py`. `Tool` subclass with `name="get_stock_info"`, descriptive `description` (the model reads this), `Input` Pydantic model with `symbol: str` and `range: Literal["1D","1W","1M","3M","6M","1Y","ALL"]`. `execute()` calls `alpaca_market_data.get_latest_quote()` + `get_bars()` in parallel via `asyncio.gather`, computes `change_abs`/`change_pct`, returns `ToolResult` with: `model_payload` (small — just symbol, price, change), `ui_block` (full `StockCardBlock`), `internal_trace` (raw Alpaca responses), `upstream_api_calls` (the two Alpaca calls with status codes + latencies).
- **Acceptance:** Unit test with mocked market data service: range mapping correct; output shape matches StockCardBlock; internal_trace contains both raw responses.
- **Files:** `app/ai/tools/get_stock_info.py`, `tests/ai/unit/test_get_stock_info.py`
- **Depends on:** C2.3, C1.1, C1.3
- **Estimate:** L

**C2.5 — Register tool with the registry**
- In `app/ai/tools/__init__.py` (or wherever the registry is constructed in `lifecycle.py`), instantiate `GetStockInfoTool` and register it. The endpoint passes the populated registry into `run_agent_turn`.
- **Acceptance:** Integration test: send a message that should trigger the tool; tool is invoked; response includes the StockCardBlock; `tool_executions` row persisted.
- **Files:** `app/ai/tools/__init__.py` (or `app/lifecycle.py`), `tests/ai/integration/test_get_stock_info_e2e.py`
- **Depends on:** C2.4, C1.2
- **Estimate:** S

#### Issues — `area:ios` (SSE & streaming state)

**C3.1 — `SSEClient` actor**
- New `Sevino/Sevino/Services/Chat/SSEClient.swift`. Actor on `URLSession.bytes(for:)`. Custom line-buffer that parses `event:`/`data:`/`id:` per the SSE spec. Exposes `func stream(request: URLRequest) -> AsyncThrowingStream<RawSSEEvent>`. Header provider closure for auth. Unit-testable parser separated from networking.
- **Acceptance:** Unit test: feed it a multi-event byte sequence, asserts events parsed correctly, including events split across `read` boundaries; manual integration test against a local server (after C3.2/C3.3) shows live events.
- **Files:** `Sevino/Sevino/Services/Chat/SSEClient.swift`, `Sevino/SevinoTests/Chat/SSEClientTests.swift`
- **Depends on:** B2.3 (wire format must be stable)
- **Estimate:** L

**C3.2 — `SSEEvent` enum decoder**
- New `Sevino/Sevino/Models/Chat/SSEEvent.swift`. `enum SSEEvent: Decodable` with associated values per backend variant (mirrors B1.2). Custom `init(from:)` checks the wire-level `event` field discriminator. Loud `os_log` decode-failure logging in DEBUG builds.
- **Acceptance:** Unit test round-trips known wire JSON for each variant; decode failure surfaces a clear error in DEBUG.
- **Files:** `Sevino/Sevino/Models/Chat/SSEEvent.swift`, `Sevino/SevinoTests/Chat/SSEEventTests.swift`
- **Depends on:** C3.1, B1.2
- **Estimate:** M

**C3.3 — `Message` struct + `Block` enum**
- New `Sevino/Sevino/Models/Chat/Message.swift` and `Sevino/Sevino/Models/Chat/Block.swift`. `struct Message { id: UUID; role: Role; var blocks: [Block] }` (`var` because blocks update via `block_data` patches). `enum Block: Codable, Identifiable` matching backend variants (text, status, stock_card). Each block addressable by `block_id`.
- **Acceptance:** Unit test: round-trip JSON for each block type; `block_id` mutation patches a block in-place within `var blocks: [Block]` array.
- **Files:** `Sevino/Sevino/Models/Chat/Message.swift`, `Sevino/Sevino/Models/Chat/Block.swift`, `Sevino/SevinoTests/Chat/BlockDecodingTests.swift`
- **Depends on:** B1.1, C1.3
- **Estimate:** M

**C3.4 — `ConversationStore` (`@Observable @MainActor`)**
- New `Sevino/Sevino/ViewModels/Chat/ConversationStore.swift`. `@Observable @MainActor final class ConversationStore` owning `messages: [Message]`, `state: TurnState`, `currentTurnId: UUID?`. Method `func send(text: String) async throws` — generates idempotency UUID, opens an SSE stream via `SSEClient`, applies events to message list (`turn_started` appends a new assistant message; `block_start`/`block_data`/`block_end` patch the current message's blocks; `turn_completed` flips state to idle; `error` flips state to error). Replaces `Sevino/Sevino/Services/ChatService.swift` placeholder.
- **Acceptance:** Unit test with a mocked `SSEClient`: feed a scripted event sequence, assert final `messages` array matches expectation; mid-stream error surfaces correctly.
- **Files:** `Sevino/Sevino/ViewModels/Chat/ConversationStore.swift`, `Sevino/Sevino/Services/Chat/MockSSEClient.swift` (test helper), `Sevino/SevinoTests/Chat/ConversationStoreTests.swift`. Delete `Sevino/Sevino/Services/ChatService.swift` placeholder.
- **Depends on:** C3.1, C3.2, C3.3
- **Estimate:** L

#### Issues — `area:ios` (chat UI)

**C4.1 — Add `swift-markdown-ui` SPM dep + `TextBlockView`**
- Add `swift-markdown-ui` (gonzalezreal/swift-markdown-ui, ^2.4) to `Sevino.xcodeproj` SPM dependencies. New `Sevino/Sevino/Views/Chat/Blocks/TextBlockView.swift` rendering `TextBlock` via `Markdown(text)` with theme tied to existing Sevino colors / font scale.
- **Acceptance:** Preview renders bold, italic, lists, code blocks correctly; theme matches existing chat aesthetic.
- **Files:** `Sevino.xcodeproj/project.pbxproj` (SPM ref), `Sevino/Sevino/Views/Chat/Blocks/TextBlockView.swift`
- **Depends on:** C3.3
- **Estimate:** M

**C4.2 — `StatusPillView`**
- New `Sevino/Sevino/Views/Chat/Blocks/StatusPillView.swift`. Renders `StatusBlock` as a muted pill — animated activity dots when `state == .active`, checkmark when `.complete`, x-mark when `.failed`. Smooth state transitions.
- **Acceptance:** Preview shows all three states; transitions animate.
- **Files:** `Sevino/Sevino/Views/Chat/Blocks/StatusPillView.swift`
- **Depends on:** C3.3
- **Estimate:** M

**C4.3 — `StockCardView`**
- New `Sevino/Sevino/Views/Chat/Blocks/StockCardView.swift`. Renders `StockCardBlock` matching the attached design: header row (logo, symbol, company name), price + change row, Swift Charts line chart (`Chart { LineMark(...) }`), range pill row (1D/1W/1M/3M/6M/1Y/ALL). Tapping a range pill is non-functional in v0 (just visual selected state — re-fetching with a different range is post-v0).
- **Acceptance:** Preview matches design; chart animates as `block_data` patches add bars; range pills render selected state correctly.
- **Files:** `Sevino/Sevino/Views/Chat/Blocks/StockCardView.swift`
- **Depends on:** C3.3
- **Estimate:** L

**C4.4 — `MessageListView`**
- New `Sevino/Sevino/Views/Chat/MessageListView.swift`. `ScrollViewReader` + `LazyVStack` rendering `[Message]` from `ConversationStore`. One row per message; each message renders its blocks in a `VStack`. Auto-scrolls to bottom on new content. Keyboard-aware bottom padding.
- **Acceptance:** Preview with a fixture conversation (3 messages, mixed block types) renders correctly; auto-scroll works.
- **Files:** `Sevino/Sevino/Views/Chat/MessageListView.swift`
- **Depends on:** C3.3, C3.4, C4.1, C4.2, C4.3
- **Estimate:** M

**C4.5 — `HomeView` integration: overlay message list**
- Modify `Sevino/Sevino/Views/Home/HomeView.swift`: when `conversationStore.messages.isEmpty == false`, hide the greeting + suggestions, show `MessageListView` filling the main content area above the existing `HomeChatInputBar`. When messages are empty, show the existing greeting/suggestions UI.
- **Acceptance:** Empty state matches today's home; sending a message switches to the message-list state cleanly; back-to-empty (e.g., new chat) is supported (defer "new chat" button to post-v0 — for v0 a force-quit/reopen is fine).
- **Files:** `Sevino/Sevino/Views/Home/HomeView.swift` (modified), `Sevino/Sevino/ViewModels/Home/HomeViewModel.swift` (hold a `ConversationStore` reference)
- **Depends on:** C4.4
- **Estimate:** M

**C4.6 — Wire `HomeChatInputBar.onSend` → `ConversationStore.send`**
- Modify the closure `HomeView` passes to `HomeChatInputBar`. Convert the input bar's `[MessageSegment]` (which carries `$AAPL`-style ticker mentions) to plain text for v0 (mentions become inline text — proper tool-aware mention handling is post-v0). Call `await conversationStore.send(text: …)`.
- **Acceptance:** Typing a message and tapping send triggers an SSE turn; UI shows assistant streaming.
- **Files:** `Sevino/Sevino/Views/Home/HomeView.swift` (modified)
- **Depends on:** C4.5, C3.4
- **Estimate:** S

**C4.7 — Auth integration (zero new code)**
- Pass `tokenProvider: { await AuthService.shared.accessToken }` to `SSEClient` constructor. No new file. Documented as a one-line change in the SSEClient init site within `ConversationStore`.
- **Acceptance:** Real device test: SSE request includes `Authorization: Bearer <jwt>`; expired tokens are refreshed by Supabase SDK before retry.
- **Files:** `Sevino/Sevino/ViewModels/Chat/ConversationStore.swift` (one-line change)
- **Depends on:** C3.4
- **Estimate:** S

#### Issues — `area:schema`, `area:ci` (schema sync + final smoke)

**C5.1 — JSON schema export from Pydantic**
- New `make ai-schema-export` target running a small Python script that imports the `Block` and `SSEEvent` discriminated unions and writes their `.model_json_schema()` to `app/ai/schema/v1.json`. Committed to the repo.
- **Acceptance:** Running the make target produces a deterministic JSON file (sorted keys, stable ordering); pre-commit hook (or CI) fails if the committed file is stale.
- **Files:** `Makefile`, `scripts/export_ai_schema.py`, `app/ai/schema/v1.json`
- **Depends on:** C1.3
- **Estimate:** M

**C5.2 — CI diff check on schema sync**
- Modify `.github/workflows/ci.yml`: new job `schema-check` runs `make ai-schema-export` and `git diff --exit-code app/ai/schema/v1.json` — fails if the export doesn't match the committed file. iOS variant-name check (compare against `Sevino/Sevino/Models/Chat/Block.swift` — extract `case` names via grep, compare to JSON variant names).
- **Acceptance:** CI fails on a PR that changes Pydantic Block without updating committed JSON; CI fails on a PR that changes Pydantic Block + JSON without updating Swift enum variants; CI green on a coordinated change.
- **Files:** `.github/workflows/ci.yml` (modified), `scripts/check_swift_block_sync.sh`
- **Depends on:** C5.1, C3.3
- **Estimate:** M

**C5.3 — Smoke case: AMD price query**
- New `tests/ai/smoke/test_get_stock_info.py`. Sends "how is AMD doing" via real Anthropic + real Alpaca sandbox; asserts response stream contains a `block_start` for `stock_card`; asserts `tool_executions` row populated with `internal_trace`, `ui_blocks_emitted`, `upstream_api_calls`.
- **Acceptance:** Test passes against real services within 15s; full audit trail visible in DB.
- **Files:** `tests/ai/smoke/test_get_stock_info.py`
- **Depends on:** C2.5, B4.1
- **Estimate:** M

#### Project C — Parallelization & critical path

```
Wave 1 (start as soon as Project B's B2.3 ships — wire format stable):
  C1.1 (SEV-494) Tool framework
  C1.3 (SEV-496) StockCardBlock schema       (after B1.1)
  C2.1 (SEV-498) Acquire Alpaca creds        (action item, day 1)
  C3.1 (SEV-503) iOS SSEClient
  C5.1 (SEV-514) JSON schema export          (after C1.3)
  C5.2 (SEV-515) CI diff check               (after C5.1, C3.3 — wave 2)

Wave 2 (after Wave 1):
  C1.2 (SEV-495) Wire ToolContext into loop  ← C1.1, A1.6
  C1.4 (SEV-497) Wire tool→SSE blocks        ← C1.2, C1.3, B2.4
  C2.2 (SEV-499) AlpacaMarketDataService     ← C2.1
  C3.2 (SEV-504) iOS SSEEvent decoder        ← C3.1, B1.2
  C3.3 (SEV-505) iOS Message + Block         ← B1.1, C1.3

Wave 3 (after Wave 2):
  C2.3 (SEV-500) Market data lifecycle       ← C2.2
  C3.4 (SEV-506) iOS ConversationStore       ← C3.1, C3.2, C3.3
  C4.1 (SEV-507) TextBlockView               ← C3.3
  C4.2 (SEV-508) StatusPillView              ← C3.3
  C4.3 (SEV-509) StockCardView               ← C3.3

Wave 4 (after Wave 3):
  C2.4 (SEV-501) get_stock_info tool         ← C2.3, C1.1, C1.3
  C4.4 (SEV-510) MessageListView             ← C3.3, C3.4, C4.1-4.3

Wave 5 (after Wave 4):
  C2.5 (SEV-502) Register tool               ← C2.4, C1.2
  C4.5 (SEV-511) HomeView integration        ← C4.4
  C4.6 (SEV-512) Wire input bar              ← C4.5, C3.4
  C4.7 (SEV-513) Auth wiring                 ← C3.4 (one-line, can ship anytime)

Wave 6 (after Wave 5):
  C5.3 (SEV-516) Smoke: AMD price            ← C2.5, B4.1
                                                  *** FINAL DEMO ***
```

**Critical paths (two parallel, by domain):**
- **Backend:** `C1.1 (SEV-494) → C1.2 (SEV-495) → C1.4 (SEV-497) → C2.4 (SEV-501) → C2.5 (SEV-502) → C5.3 (SEV-516)` (~3 days)
- **iOS:** `C3.1 (SEV-503) → C3.2 (SEV-504) → C3.4 (SEV-506) → C4.4 (SEV-510) → C4.5 (SEV-511) → C4.6 (SEV-512)` (~3 days, runs alongside backend)
- Integration day at the end where C5.3 (SEV-516) tests the full backend + iOS round trip.

**For three engineers (1 backend, 1 iOS, 1 floater):**
- **E1 (backend tools):** C1.1 (SEV-494) → C1.2 (SEV-495) → C1.4 (SEV-497) → C2.4 (SEV-501) → C2.5 (SEV-502) → C5.3 (SEV-516)
- **E2 (iOS):** C3.1 (SEV-503) → C3.2 (SEV-504) → C3.3 (SEV-505) → C3.4 (SEV-506) → C4.4 (SEV-510) → C4.5 (SEV-511) → C4.6 (SEV-512)
- **E3 (supporting):** C2.1 (SEV-498), C2.2 (SEV-499), C2.3 (SEV-500) (alpaca client) → C1.3 (SEV-496), C5.1 (SEV-514), C5.2 (SEV-515) (schema sync) → C4.1 (SEV-507), C4.2 (SEV-508), C4.3 (SEV-509) (block views, can hand off to E2)

iOS engineer (E2) can start with C3.1 (SEV-503) (SSE parser — tested locally with a captured SSE stream from B2.3) on day 1 of Project C, before any backend tool work has shipped. The wire format is stable from B2.3.

---

### Cross-project sizing & critical path

| Project | Issues | LoC (rough) | Days (1 eng) | Days (2-3 eng) |
|---|---|---|---|---|
| A: Foundation | 17 | ~1500 | 4-5 | 2-3 |
| B: Streaming & Safety | 11 | ~1200 | 3-4 | 2-3 |
| C: Tools & Chat Surface | 21 | ~2500 | 6-7 | 3-4 (across BE+iOS) |
| **Total** | **49** | **~5200** | **13-16** | **7-10** |

**Two-week wall-clock target is realistic with 2-3 engineers.** Critical path: A → B → C-backend, with iOS shadowing C-backend.

**External blockers:**
- D1 / C2.1 — Alpaca Market Data sandbox creds. Should be acquired during Project A so they're ready for Project C. No code dependency, just an action item on someone with Alpaca dashboard access.
- Anthropic API key with prompt caching + extended thinking — needed for A1.1.
- Langfuse Cloud account — needed for A3.1.

---

## Appendix: items NOT in v0 (just so they're written down)

Confirmed deferred per spec — flagged here only when a v0 design choice makes them *easier* later:

- **Profile Card / holdings injection into context** — v0 system prompt has a `<user_context>` section that's empty for now; injecting holdings is a one-liner change later.
- **Trade proposal flow** — `tool_executions.parent_tool_execution_id` self-FK + the `ToolContext.parent_emitter` pattern make trade-flow as a sub-tool trivial.
- **Conversation list UI / GET endpoint** — `conversations.last_message_at` is updated on every turn (item 10), so this becomes a one-route addition.
- **SSE resumption after long disconnect** — events carry `id:` from day one (item 12), so adding `Last-Event-ID` resume on reconnect is post-v0 work that doesn't change the protocol.
- **Multi-agent** — `agent_role` on `model_invocations` and `parent_tool_execution_id` on `tool_executions` exist from day one (item 9). The agent loop is parameterised (item 3) — a sub-agent is just `await run_agent_turn(...)` from inside a tool's `execute()`.
- **Daily cost rollup** — `agent_turns.total_cost_usd_micros` is per-turn; rollup is `SELECT date_trunc('day'…) GROUP BY user_id` whenever you add the table.

---

## Confidence + open follow-ups

**High confidence (codebase verified):**
- Backend conventions, middleware order, error taxonomy, repository pattern, SSE listener pattern, ARQ setup, Sentry, slowapi, structlog, JWT flow, iOS auth, iOS chat input bar.

**Medium confidence (assumed but not directly verified):**
- That `sse-starlette` + slowapi play nicely under load (R3).
- That Anthropic's `await stream.close()` cancels server-side billing fast enough to trust (R4).
- That swift-markdown-ui hits acceptable perf on 50Hz delta updates (R7).

**Things you need to do outside this plan:**
1. Acquire Alpaca Market Data sandbox credentials.
2. Create Anthropic API key with prompt caching + extended thinking access.
3. Create Langfuse Cloud account, get project key.
4. Decide what happens to the existing `Conversation Persistence` Linear project once the migration lands (close, repurpose, or fold into `AI — Foundation`).
