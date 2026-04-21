# Real-Time Events System — Implementation Plan

## Context

Alpaca pushes out-of-band updates to us via four persistent connections (three SSE + one WebSocket). Today we have none of the infrastructure to consume them: no SSE client, no WebSocket client, no checkpoint storage, no long-running listener base, and no handlers wired into the ARQ worker. Without these, KYC decisions, ACH transfer lifecycle transitions, and order fills are only observable via polling, which the app isn't designed to do.

This plan implements the full system per `sevino-api/docs/architecture.md` §Real-Time Events, closing:

- **SEV-186** — SSE connection infrastructure (base listener + checkpoint table)
- **SEV-217** — WebSocket client infrastructure (base listener + deployment model)
- **SEV-213** — Alpaca account status SSE listener
- **SEV-214** — Alpaca transfer status SSE listener
- **SEV-216** — Alpaca trade events SSE listener (fallback)
- **SEV-215** — Alpaca trade updates WebSocket listener (primary)

### Design decisions taken (architecture wins)

Tickets SEV-213/214/215/216 described richer schemas than the architecture. The architecture is authoritative:

- **Transfer status events** do not write to a DB table — they only invalidate cache and fire (future) notifications. No `transfers` model is added. SEV-214's "transfers table" language is superseded.
- **Trade events** update the existing `order_events` row in place; no separate `orders` + audit-log split. SEV-215/216's "orders + order_events" language is superseded.
- **Out-of-order protection** uses an explicit status-lifecycle ordering map, not timestamp comparison. SEV-215's timestamp-based approach is superseded.
- **SEV-216 shadow mode** is not implemented. Dedup is natural via UPDATE idempotency — no toggle needed.
- **No caching layer for MVP.** The app reads live data from Alpaca on every request. Handlers that the architecture describes as "invalidate cache" become no-ops (or log-only) for now. When caching is introduced later, invalidation calls get slotted back in at the same handler boundaries.

### Constraints worth naming up front

- Alpaca enforces **one SSE connection per stream and one WebSocket per API key**. That is the source of our single-consumer guarantee — we do not need leader election, we just need **Railway `replicas=1` on the worker service** and to keep listeners off the `web` service.
- Listeners run as `asyncio.Task`s inside the existing ARQ worker process, spawned in the `on_startup` hook and cancelled in `on_shutdown`. No new Railway service is introduced.
- The FastAPI web process never touches these connections.

---

## Critical files to modify / add

**New:**
- `app/models/sse_checkpoint.py` — `SseCheckpoint` ORM model
- `app/repositories/sse_checkpoint.py` — get/upsert checkpoint helpers
- `app/listeners/__init__.py` — new package for long-running listeners
- `app/listeners/base_sse.py` — SSE base class (SEV-186)
- `app/listeners/base_ws.py` — WebSocket base class (SEV-217)
- `app/listeners/account_status.py` — SEV-213 listener
- `app/listeners/transfer_status.py` — SEV-214 listener
- `app/listeners/trade_events_sse.py` — SEV-216 listener
- `app/listeners/trade_events_ws.py` — SEV-215 listener
- `app/services/account_events.py` — `handle_account_status_change`
- `app/services/transfer_events.py` — `handle_transfer_status_change`
- `app/services/trade_events.py` — `handle_trade_update` + status ordering map
- `migrations/versions/<new>_add_sse_checkpoints.py`
- `docs/architecture.md` — §"Worker topology" subsection added (SEV-217)

**Modified:**
- `app/worker.py` — wire listener startup/shutdown into `on_startup`/`on_shutdown`
- `app/services/alpaca_broker.py` — add `get_open_orders()`, `get_recently_updated_accounts()` helpers for reconcile-on-reconnect (minor additions only)
- `migrations/env.py` — import `SseCheckpoint`
- `app/models/__init__.py` — export `SseCheckpoint`
- `pyproject.toml` — add `httpx-sse`, `websockets`

---

## SEV-186 — SSE connection infrastructure

Foundation for every SSE listener. Must land first.

1. **Add dependency.** `httpx-sse` (thin layer over our existing `httpx` async client; no new HTTP stack).
2. **Create `sse_checkpoints` table.** One row per stream. Columns: `stream_name` (text PK), `last_event_id` (text, nullable — null on first-ever deploy), `updated_at` (timestamptz, auto-updated on write). Plus the standard `created_at`. No user scoping — these are process-level.
3. **Model + repository.** `SseCheckpoint` ORM model, `SseCheckpointRepository` with `get(stream_name)`, `upsert(stream_name, last_event_id)`. Register model in `migrations/env.py`.
4. **Base SSE listener class** (`app/listeners/base_sse.py`). Responsibilities:
   - Open long-lived `GET` via `httpx-sse` against the configured Alpaca endpoint, with OAuth bearer token sourced from `AlpacaBrokerService._get_token()` (reuse, do not duplicate).
   - On connect, read checkpoint and append `?since_id=<last_event_id>` when present; otherwise connect without it (stream-from-now on first deploy / lost checkpoint).
   - Parse each event block into `(event_type, event_id, data_json)`; dispatch to a subclass-provided async handler.
   - Update checkpoint **after** the handler returns successfully (so crashes during handling are safe — we'll re-replay).
   - Bind a new correlation ID per event to structlog contextvars for the duration of the handler.
   - Capture Sentry breadcrumbs on connect, disconnect, parse-failure; capture exceptions in handlers without killing the loop.
   - Expose a `last_message_received_at` attribute (monotonic) — used by the health/liveness probe.
   - Reconnect on any disconnect or parse failure with exponential backoff + jitter. No max retry cap — listeners run forever.
   - Respond to `asyncio.CancelledError` cleanly: close the stream, flush the final checkpoint if possible, exit.
5. **Liveness signal.** Each listener exposes its `last_message_received_at`. A lightweight ARQ cron job (every 5 min) checks all registered listeners; if any has been silent longer than its configured threshold, emit a Sentry `capture_message` (not an exception) with the stream name. Thresholds are per-stream (account status may be silent for hours legitimately; trade events should not).
6. **Worker integration hook.** `app/worker.py` gains a registry pattern: a module-level list of listener instances that `on_startup` iterates to spawn `asyncio.create_task`, and `on_shutdown` iterates to cancel + await. Store task handles on `ctx` for debuggability.
7. **Worker topology documentation.** Add a subsection to `docs/architecture.md` §Deployment explicitly stating: worker service runs with `replicas=1`; Alpaca's per-API-key limit enforces single-consumer; no leader election. Call this out as a **deploy-time invariant**.
8. **Tests.** Unit-test the base class with a fake httpx transport that streams canned SSE text: verify parsing, checkpoint updates, reconnect on disconnect, `since_id` replay on reconnect, correlation-ID binding, graceful cancel.

**Done when:** checkpoint table exists, base listener class unit-tested, worker integration hooks in place but no concrete listeners yet (those are SEV-213/214/216).

---

## SEV-217 — WebSocket client infrastructure

Parallel foundation for WebSocket listeners. Can land alongside SEV-186.

1. **Add dependency.** `websockets` (pure asyncio WS client, well-maintained, no extra HTTP baggage). Rationale for choice: `httpx-ws` pins to httpx's TLS stack which has had edge cases with long-lived connections; `aiohttp` brings an entire second HTTP stack. `websockets` is the narrowest fit.
2. **Base WebSocket listener class** (`app/listeners/base_ws.py`). Responsibilities:
   - Connect to configured `wss://` URL.
   - Post-connect auth step: subclass-provided async `authenticate()` (for Alpaca: send JSON auth frame with key/secret, await ack).
   - Post-auth subscribe step: subclass-provided async `subscribe()` (for Alpaca: send subscribe frame listing streams).
   - Receive loop: dispatch each message to subclass-provided async handler.
   - Ping/pong heartbeat configured via `websockets` built-in `ping_interval`/`ping_timeout`. On timeout, treat as disconnect.
   - Reconnect with exponential backoff + jitter; re-run auth + subscribe; call subclass-provided `on_reconnect()` for reconcile sweeps.
   - Correlation ID per message, Sentry breadcrumbs, exception capture without loop death — mirror the SSE base contract.
   - `last_message_received_at` for liveness parity with SSE.
   - Graceful shutdown on `asyncio.CancelledError`.
3. **Liveness signal.** Reuse the same cron-driven checker from SEV-186 (registry includes both SSE and WS listeners).
4. **Worker integration.** Reuse the listener registry pattern introduced in SEV-186.
5. **Config.** Add `alpaca_ws_url` as a computed property on `Settings` (sandbox vs prod — already a pattern there), plus env-tunable defaults for heartbeat interval and reconnect caps.
6. **Railway deployment model.** Document in `docs/architecture.md` §Deployment:
   - Listener runs inside existing `worker` Railway service (not a new one) — cheaper, and keeps the single-consumer invariant trivial.
   - `replicas=1` is required.
   - Procfile unchanged.
   - No separate health check endpoint needed; liveness bubbles up through Sentry.
7. **Tests.** Unit-test with a fake WS transport: auth/subscribe sequencing, reconnect re-subscribes, heartbeat failure triggers reconnect, graceful cancel.

**Done when:** `BaseWebSocketListener` ready, worker deploy model documented, no concrete listener yet (that's SEV-215).

---

## SEV-213 — Account status SSE listener

Depends on SEV-186.

1. **Listener class** (`app/listeners/account_status.py`). Subclass of `BaseSSEListener`. Stream name `account_status`. Endpoint `/v1/events/accounts/status` on the Broker API. Silence threshold: long (hours) — KYC is genuinely infrequent.
2. **Handler service** (`app/services/account_events.py`). Single function `handle_account_status_change(db, event_payload)`:
   - Look up `brokerage_accounts` by `alpaca_account_id`. If not ours, skip silently (Alpaca returns all accounts on the master key).
   - Update `account_status` to the new value.
   - If new status is `ACTIVE`: call Alpaca REST to enroll FDIC sweep, set `activated_at = now()`. (FDIC enrollment lives on `AlpacaBrokerService` as a new method.)
   - Idempotent by construction: repeat events UPDATE to the same terminal value.
3. **Reconcile-on-reconnect.** `on_reconnect()` hook fetches `BrokerageAccountRepository.get_pending()` (already exists) and for each account, calls Alpaca REST `get_account(...)` to refresh status. Bounded by the count of non-terminal accounts — small.
4. **Wire into worker registry.**
5. **Tests.**
   - Unit: handler correctly updates row, triggers FDIC enrollment on ACTIVE.
   - Unit: handler skips unknown account IDs.
   - Integration (real Postgres): end-to-end through a fake SSE transport emitting synthetic events.

---

## SEV-214 — Transfer status SSE listener

Depends on SEV-186. **Per architecture, this does NOT write to the DB. With caching removed for MVP, the handler is essentially a pass-through for now — the listener is still wired up so we capture events, but the handler body is minimal.**

1. **Listener class** (`app/listeners/transfer_status.py`). Stream name `transfer_status`. Endpoint `/v1/events/transfers/status`. Silence threshold: medium (deposits are rare-ish, but ACH lifecycle is hours not days).
2. **Handler service** (`app/services/transfer_events.py`). Single function `handle_transfer_status_change(db, event_payload)`:
   - Resolve `account_id` → our user via `brokerage_accounts.alpaca_account_id`; skip unknowns silently.
   - Log the transition (status_from → status_to, amount, transfer_id) for observability.
   - Leave a hook/TODO marker for a future push-notification side-effect (out of scope for this ticket — just keep the shape ready).
   - No DB writes, no cache invalidation. When caching or push notifications are added later, this is where they'll hook in.
3. **No DB reconciliation needed on reconnect** — there's no local state to reconcile. SSE `since_id` replay is sufficient.
4. **Wire into worker registry.**
5. **Tests.** Unit: handler parses events correctly, skips unknown accounts, logs as expected.

**Note for implementation:** if during implementation you discover we do need any transfer-state tracking (e.g. for the iOS app's deposit-pending UI), stop and surface it — that's a scope decision, not a silent expansion.

---

## SEV-216 — Trade events SSE listener (fallback)

Depends on SEV-186 and on the shared trade handler. Lands alongside SEV-215.

1. **Listener class** (`app/listeners/trade_events_sse.py`). Stream name `trade_events_sse`. Endpoint `/v1/events/trades`. Silence threshold: short — trade events are continuous during market hours.
2. **Handler:** reuses `handle_trade_update` from `app/services/trade_events.py` (shared with SEV-215). **No handler code lives in this ticket.**
3. **Reconcile-on-reconnect.** `on_reconnect()` queries open orders (status not in `{filled, canceled, expired, rejected}`) and fetches latest state from Alpaca REST per order. Requires a new `OrderEventRepository.get_open()` method.
4. **Wire into worker registry.**
5. **Tests.** Integration test that fires events through both WS and SSE transports simultaneously and asserts the final DB row is correct exactly once (no double-applied fills, no status regressions).

---

## SEV-215 — Trade updates WebSocket listener (primary)

Depends on SEV-217. **Owns the shared trade handler.**

1. **Shared trade handler** (`app/services/trade_events.py`).
   - `STATUS_ORDER: dict[str, int]` — explicit lifecycle map: `{new, accepted_for_bidding, accepted, pending_new, partially_filled, filled, done_for_day, canceled, expired, replaced, pending_cancel, pending_replace, rejected, suspended, calculated, stopped}` → ordinal. Terminal states get the highest ordinals. Source the exact set from Alpaca docs when implementing.
   - `handle_trade_update(db, event_payload)`:
     - Look up `order_events` by `alpaca_order_id`. Skip unknown.
     - Read current `status`; compare ordinal of incoming vs current via `STATUS_ORDER`. If incoming ≤ current, skip (stale/out-of-order).
     - UPDATE `status`, `filled_avg_price`, `filled_qty`, `filled_at` (where present on the event).
     - Idempotent by construction.
2. **Listener class** (`app/listeners/trade_events_ws.py`). Subclass of `BaseWebSocketListener`. Connects to sandbox or prod `wss://broker-api[.sandbox].alpaca.markets/stream`. `authenticate()` sends Alpaca's JSON auth frame. `subscribe()` sends `listen` frame for `trade_updates`. Message handler calls `handle_trade_update`.
3. **Reconcile-on-reconnect.** Same as SEV-216 — query open orders, refresh via REST. Extract into a helper in `app/services/trade_events.py` so both listeners share it.
4. **Wire into worker registry.**
5. **Coexistence with SEV-216.** Both routes call `handle_trade_update`. Dedup is UPDATE-idempotency + the status-ordering skip; no additional dedup keys, no Redis locks. The tests in SEV-216 verify this empirically.
6. **Tests.**
   - Unit: status ordering map rejects regressions, accepts forward transitions, handles equal-status (no-op update is fine).
   - Unit: partial-fill cumulative logic — confirm the event's `filled_qty` is Alpaca's cumulative (not delta); if not, adjust handler (expected: Alpaca reports cumulative).
   - Integration: full WS handshake against a fake transport, subscribe, receive, handle, disconnect, reconnect + resubscribe.

---

## Order of execution

1. SEV-186 + SEV-217 in parallel (foundations). Both must merge before any consumer.
2. SEV-213 + SEV-214 in parallel (both consume SEV-186, touch disjoint files).
3. SEV-215 lands next, introducing the shared `handle_trade_update` + status map.
4. SEV-216 lands last, reusing SEV-215's handler.

Each ticket should ship as its own PR, small enough to review independently.

---

## Verification

**Per ticket:** unit tests + integration tests as described above, plus `make test` green locally.

**End-to-end on staging (after all six merge):**

1. Deploy to Railway staging. Confirm worker service has `replicas=1`; confirm `web` service is unchanged.
2. Tail worker logs. Confirm all four listeners report "connected" at startup, with correlation IDs and empty/last checkpoints logged.
3. **Account status:** submit a new KYC via the existing onboarding flow in sandbox. Watch the worker process the `account_status` event, see `brokerage_accounts.account_status` transition to `ACTIVE` in Supabase Studio, confirm `activated_at` set, confirm FDIC enrollment called.
4. **Transfer status:** initiate a sandbox ACH deposit via Alpaca directly (no UI yet). Watch the worker log the `transfer_status` event. Confirm no DB write.
5. **Trade events:** submit a sandbox order via Alpaca directly. Confirm both the WS listener and the SSE listener log the fill; confirm `order_events` row updates exactly once (check `updated_at` timestamp — only one transition).
6. **Reconnect:** restart the Railway worker service. Confirm each listener reads its checkpoint, reconnects with `since_id`, and processes any missed events (test by emitting an event while the worker is down if Alpaca sandbox supports it; otherwise verify checkpoint semantics via unit test only).
7. **Liveness:** temporarily lower the silence threshold on one listener to 30s and stop emitting events to it; confirm Sentry `capture_message` fires.
8. **Out-of-order:** use a sandbox-scriptable test where feasible — otherwise rely on unit tests for status-map skips.
9. `uv run alembic heads` shows a single head.
