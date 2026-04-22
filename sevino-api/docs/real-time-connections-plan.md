# Real-Time Events System — Implementation Plan

## Context

Alpaca pushes out-of-band updates to us via three persistent SSE connections. Today we have none of the infrastructure to consume them: no SSE client, no checkpoint storage, no long-running listener base, and no handlers wired into the ARQ worker. Without these, KYC decisions, ACH transfer lifecycle transitions, and order fills are only observable via polling, which the app isn't designed to do.

This plan implements the full system per `sevino-api/docs/architecture.md` §Real-Time Events, closing:

- **SEV-186** — SSE connection infrastructure (base listener + checkpoint table)
- **SEV-213** — Alpaca account status SSE listener
- **SEV-214** — Alpaca transfer status SSE listener
- **SEV-216** — Alpaca trade events SSE listener
- **SEV-217** — _(repurposed)_ Documentation update removing the WebSocket-based design; see the ticket for the rationale.
- **SEV-215** — _(superseded)_ Originally scoped as an Alpaca trade updates WebSocket listener (primary). The Broker API does not offer a WebSocket endpoint for trade updates, so the trade events SSE stream (SEV-216) is now the sole path. Any remaining work on SEV-215 folds into SEV-216.

### Design decisions taken (architecture wins)

Tickets SEV-213/214/216 described richer schemas than the architecture. The architecture is authoritative:

- **Transfer status events** do not write to a DB table — they only invalidate cache and fire (future) notifications. No `transfers` model is added. SEV-214's "transfers table" language is superseded.
- **Trade events** update the existing `order_events` row in place; no separate `orders` + audit-log split. The "orders + order_events" language from earlier ticket drafts is superseded.
- **No caching layer for MVP.** The app reads live data from Alpaca on every request. Handlers that the architecture describes as "invalidate cache" become no-ops (or log-only) for now. When caching is introduced later, invalidation calls get slotted back in at the same handler boundaries.
- **No dedup / out-of-order handling needed.** SSE delivers events sequentially over a single connection per stream, and handlers are UPDATE-idempotent — replay after reconnect is safe without extra machinery. (The earlier status-lifecycle ordering map was designed to reconcile SSE+WS races; with SSE only, it's not required.)

### Constraints worth naming up front

- Alpaca's Broker API allows **up to 25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)). All non-prod environments share a single sandbox key, so 25 is the ceiling across dev + staging + PR previews combined. Budget: 3 local dev + 1 staging + up to 21 PR previews. See `docs/architecture.md` §Worker topology.
- Each environment's `worker` Railway service runs with `replicas=1` — scaling any one environment's worker beyond a single replica would double-consume events for that environment.
- Listeners run as `asyncio.Task`s inside the existing ARQ worker process, spawned in the `on_startup` hook and cancelled in `on_shutdown`. No new Railway service is introduced.
- The FastAPI web process never touches these connections.

---

## Critical files to modify / add

**New:**
- `app/models/sse_checkpoint.py` — `SseCheckpoint` ORM model
- `app/repositories/sse_checkpoint.py` — get/upsert checkpoint helpers
- `app/listeners/__init__.py` — new package for long-running listeners
- `app/listeners/base_sse.py` — SSE base class (SEV-186)
- `app/listeners/account_status.py` — SEV-213 listener
- `app/listeners/transfer_status.py` — SEV-214 listener
- `app/listeners/trade_events.py` — SEV-216 listener
- `app/services/account_events.py` — `handle_account_status_change`
- `app/services/transfer_events.py` — `handle_transfer_status_change`
- `app/services/trade_events.py` — `handle_trade_update`
- `migrations/versions/<new>_add_sse_checkpoints.py`

**Modified:**
- `app/worker.py` — wire listener startup/shutdown into `on_startup`/`on_shutdown`
- `app/services/alpaca_broker.py` — add `get_open_orders()`, `get_recently_updated_accounts()` helpers for reconcile-on-reconnect (minor additions only)
- `migrations/env.py` — import `SseCheckpoint`
- `app/models/__init__.py` — export `SseCheckpoint`
- `pyproject.toml` — add `httpx-sse`

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
7. **Worker topology documentation.** Add a subsection to `docs/architecture.md` §Deployment explicitly stating: each environment's worker service runs with `replicas=1`; Alpaca's 25-connection-per-API-key limit is shared across the sandbox fleet (dev + staging + PR previews); no leader election.
8. **Tests.** Unit-test the base class with a fake httpx transport that streams canned SSE text: verify parsing, checkpoint updates, reconnect on disconnect, `since_id` replay on reconnect, correlation-ID binding, graceful cancel.

**Done when:** checkpoint table exists, base listener class unit-tested, worker integration hooks in place but no concrete listeners yet (those are SEV-213/214/216).

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

## SEV-216 — Trade events SSE listener

Depends on SEV-186. This is now the sole real-time channel for order lifecycle events (SEV-215's WebSocket-based "primary" is superseded — see Context).

1. **Listener class** (`app/listeners/trade_events.py`). Stream name `trade_events`. Endpoint `/v2/events/trades`. Silence threshold: short — trade events are continuous during market hours. Overrides `resume_field = "event_id"` and `resume_param = "since_id"` per the v2 endpoint convention (see `docs/architecture.md` §Real-Time Events → "Resume-param overrides").
2. **Handler** (`app/services/trade_events.py`). `handle_trade_update(db, event_payload)`:
   - Look up `order_events` by `alpaca_order_id`. Skip unknown.
   - UPDATE `status`, `filled_avg_price`, `filled_qty`, `filled_at` (where present on the event).
   - Idempotent by construction — replays of the same event produce the same row state.
3. **Reconcile-on-reconnect.** `on_reconnect()` queries open orders (status not in `{filled, canceled, expired, rejected}`) and fetches latest state from Alpaca REST per order. Requires a new `OrderEventRepository.get_open()` method.
4. **Wire into worker registry.**
5. **Tests.**
   - Unit: handler updates `order_events` row correctly for fill / partial-fill / cancel / reject payloads.
   - Unit: partial-fill cumulative logic — confirm the event's `filled_qty` is Alpaca's cumulative (not delta); if not, adjust handler (expected: Alpaca reports cumulative).
   - Integration: end-to-end through a fake SSE transport emitting canned trade events; confirm `order_events` rows update; confirm `since_id` replay on reconnect.

---

## Order of execution

1. SEV-186 first (foundation). Must merge before any consumer.
2. SEV-213 + SEV-214 + SEV-216 can proceed in parallel once SEV-186 lands (they consume disjoint files).

Each ticket should ship as its own PR, small enough to review independently.

---

## Verification

**Per ticket:** unit tests + integration tests as described above, plus `make test` green locally.

**End-to-end on staging (after all four merge):**

1. Deploy to Railway staging. Confirm worker service has `replicas=1`; confirm `web` service is unchanged.
2. Tail worker logs. Confirm all three SSE listeners report "connected" at startup, with correlation IDs and empty/last checkpoints logged.
3. **Account status:** submit a new KYC via the existing onboarding flow in sandbox. Watch the worker process the `account_status` event, see `brokerage_accounts.account_status` transition to `ACTIVE` in Supabase Studio, confirm `activated_at` set, confirm FDIC enrollment called.
4. **Transfer status:** initiate a sandbox ACH deposit via Alpaca directly (no UI yet). Watch the worker log the `transfer_status` event. Confirm no DB write.
5. **Trade events:** submit a sandbox order via Alpaca directly. Confirm the trade events SSE listener logs the fill; confirm `order_events` row updates with the final status, fill price, and timestamps.
6. **Reconnect:** restart the Railway worker service. Confirm each listener reads its checkpoint, reconnects with `since_ulid`/`since_id`, and processes any missed events (test by emitting an event while the worker is down if Alpaca sandbox supports it; otherwise verify checkpoint semantics via unit test only).
7. **Liveness:** temporarily lower the silence threshold on one listener to 30s and stop emitting events to it; confirm Sentry `capture_message` fires.
8. `uv run alembic heads` shows a single head.
