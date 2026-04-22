# Architecture

This document describes how the Sevino API works — the full stack, how services connect, how data flows, and how everything deploys.

## 📑 Table of Contents

- [🌐 System Overview](#-system-overview)
- [📁 Directory Structure](#-directory-structure)
- [🔐 Authentication](#-authentication)
  - [The flow](#the-flow)
  - [JWT verification details](#jwt-verification-details)
  - [User data split](#user-data-split)
  - [API security layers](#api-security-layers)
- [🔍 Error Handling & Logging](#-error-handling--logging)
  - [Structured error responses](#structured-error-responses)
  - [Detail payloads](#detail-payloads)
  - [Request logging & correlation IDs](#request-logging--correlation-ids)
  - [Log output format](#log-output-format)
- [🗄️ Database](#-database)
  - [Connection setup](#connection-setup)
  - [Local Supabase setup](#local-supabase-setup)
  - [Dual port setup (production only)](#dual-port-setup-production-only)
  - [Migrations (Alembic)](#migrations-alembic)
  - [Handling migration conflicts](#handling-migration-conflicts)
  - [What lives in the database vs. what doesn't](#what-lives-in-the-database-vs-what-doesnt)
  - [Row Level Security](#row-level-security)
- [📈 Alpaca Integration](#-alpaca-integration)
  - [Authentication with Alpaca](#authentication-with-alpaca)
  - [Account creation & KYC](#account-creation--kyc)
  - [Trading](#trading)
  - [Portfolio data](#portfolio-data)
- [📡 Real-Time Events (SSE)](#-real-time-events-sse)
  - [Connections](#connections)
  - [How SSE works](#how-sse-works)
  - [Checkpoint & resume strategy](#checkpoint--resume-strategy)
  - [Event handlers](#event-handlers)
  - [Worker integration](#worker-integration)
- [🏦 Plaid Integration](#-plaid-integration)
  - [The flow](#the-flow-1)
- [⚙️ Background Jobs (ARQ + Redis)](#-background-jobs-arq--redis)
  - [Why background jobs](#why-background-jobs)
  - [Worker architecture](#worker-architecture)
  - [Job flow](#job-flow)
  - [Task definitions](#task-definitions)
- [🚀 Deployment](#-deployment)
  - [Hosting](#hosting)
  - [Build system](#build-system)
  - [Deploy sequence](#deploy-sequence)
  - [Environments & PR previews](#environments--pr-previews)
  - [Railway MCP server](#railway-mcp-server-for-claude-code)
  - [Monorepo configuration](#monorepo-configuration)

## 🌐 System Overview

The backend is a FastAPI application that serves as the intermediary between the Sevino iOS app and all external services. The app never talks to Alpaca, Plaid, or the database directly — everything goes through this API.

```
Sevino App (iOS)
  │
  │  HTTPS + JWT (Authorization: Bearer <token>)
  ▼
Sevino API — FastAPI (Railway)
  │
  ├──▶ Supabase Postgres     — user profiles, AI data, app state
  ├──▶ Alpaca Broker API      — accounts, KYC, trading, portfolios, custody
  ├──▶ Plaid API              — bank linking (token exchange only)
  ├──▶ LLM Provider           — AI agent inference (trade analysis, NL parsing)
  └──▶ Redis + ARQ Worker     — background job processing
```

## 📁 Directory Structure

```
sevino-api/
├── pyproject.toml          # dependencies (managed by uv)
├── uv.lock                 # pinned dependency versions
├── .python-version         # Python version pin (3.12), read by uv
├── Procfile                # Railway start commands (web + worker)
├── Makefile                # local dev shortcuts (make server, make worker, etc.)
├── alembic.ini             # migration config
├── .env                    # local env vars (gitignored)
├── .env.example            # template for other devs
├── supabase/
│   └── config.toml         # Supabase local dev config (ports, auth settings, etc.)
├── migrations/
│   ├── env.py              # Alembic environment config
│   └── versions/           # generated migration files
├── app/
│   ├── main.py             # FastAPI app, middleware wiring, exception handlers, endpoints
│   ├── config.py           # Pydantic Settings class (reads env vars / .env)
│   ├── database.py         # SQLAlchemy async engine, session factory
│   ├── auth.py             # get_current_user dependency (JWT verification)
│   ├── exceptions.py       # Custom exceptions + global error handlers
│   ├── lifecycle.py        # FastAPI lifespan (ARQ pool init/shutdown)
│   ├── logging_config.py   # structlog setup (console dev, JSON prod/staging)
│   ├── rate_limit.py       # slowapi Limiter instance, key functions, rate limit config
│   ├── middleware/          # HTTP middleware
│   │   ├── correlation.py  # X-Correlation-ID generation + structlog contextvars
│   │   └── logging.py      # Request/response access logging
│   ├── models/             # SQLAlchemy ORM models
│   │   └── base.py         # DeclarativeBase
│   ├── repositories/       # data access layer (one class per model)
│   │   ├── user_profile.py
│   │   ├── financial_profile.py
│   │   └── brokerage_account.py
│   ├── schemas/            # Pydantic request/response models
│   │   └── onboarding.py
│   ├── routes/             # API endpoint handlers
│   │   └── onboarding.py   # PATCH /v1/onboarding, POST /v1/onboarding/submit, GET /v1/onboarding/status
│   ├── services/           # business logic, external API wrappers
│   │   ├── alpaca_broker.py  # AlpacaBrokerService (OAuth2 client credentials)
│   │   └── onboarding.py     # OnboardingService (step saves + KYC submission)
│   ├── worker.py           # ARQ worker settings and config
│   └── tasks/              # background task definitions
│       └── health_ping.py  # placeholder cron task
└── tests/
    ├── conftest.py          # shared fixtures
    ├── unit/
    ├── integration/
    └── fixtures/
        └── mock_responses/
```

## 🔐 Authentication

Authentication uses Supabase Auth. The Sevino app handles signup/login via the `supabase-swift` SDK and receives a JWT. Every request to the API includes this token.

### The flow

1. User signs up or logs in on the Sevino app → Supabase Auth issues a JWT + refresh token.
2. The app stores tokens (Supabase SDK handles this) and attaches the JWT to every API request: `Authorization: Bearer <token>`.
3. FastAPI's `get_current_user` dependency (in `app/auth.py`) runs on every protected route:
   - Extracts the token from the header.
   - Verifies the signature using JWKS (JSON Web Key Set). The backend fetches the public key from Supabase's JWKS endpoint (`{SUPABASE_URL}/.well-known/jwks.json`) and verifies the token's ECC (P-256) signature using PyJWT's `PyJWKClient`. No shared secret is needed — this is asymmetric verification.
   - Checks expiration.
   - Extracts the user ID from the `sub` claim.
4. The user ID is injected into route handlers via `current_user = Depends(get_current_user)`.
5. All database queries scope to that user ID (`WHERE user_id = ...`).

### JWT verification details

Supabase uses ECC (P-256) asymmetric signing for JWTs. The backend verifies tokens using the public key published at the JWKS endpoint — no `SUPABASE_JWT_SECRET` env var is needed.

The `PyJWKClient` from PyJWT handles key fetching and caching automatically:

```python
from jwt import PyJWKClient

jwks_client = PyJWKClient(f"{SUPABASE_URL}/.well-known/jwks.json")
signing_key = jwks_client.get_signing_key_from_jwt(token)
payload = jwt.decode(token, signing_key.key, algorithms=["ES256"], audience="authenticated")
```

The JWKS endpoint is public and cacheable. `PyJWKClient` caches keys in memory and only refetches when it encounters an unknown key ID, so there's no per-request latency hit.

Locally, the Supabase CLI (`supabase start`) also exposes a JWKS endpoint at `http://127.0.0.1:54321/.well-known/jwks.json`, so the same verification code works in both environments — just point `SUPABASE_URL` at the right host.

### User data split

- `auth.users` (managed by Supabase Auth) — credentials, email, auth metadata. We don't write to this directly.
- `user_profiles` table (our SQLAlchemy model) — app-specific data: name, address, citizenship, disclosures, onboarding status, etc. Foreign-keyed to `auth.users.id`.
- `brokerage_accounts` table — Alpaca account ID, account status, KYC results. Created on KYC submission.

When a user signs up, a row in `user_profiles` is created with the same UUID, mapping the Supabase user to their onboarding and brokerage records.

### API security layers

1. **JWT authentication** (primary) — Supabase Auth tokens verified via JWKS on every request.
2. **HTTPS** — Railway provides TLS automatically.
3. **API key** — static key embedded in the Sevino app, sent as `X-API-Key` header. Checked by middleware. Prevents casual abuse.
4. **Rate limiting** — implemented via slowapi + Redis (`app/rate_limit.py`). Two tiers:
   - **Authenticated routes (default):** `120/minute` per user — keyed by `request.state.user_id` (set by `get_current_user`), falls back to client IP for unauthenticated requests.
   - **Auth endpoints (strict):** `10/minute` per IP — applied via `@limiter.limit("10/minute", key_func=get_remote_address)` decorator on login/signup routes.
   - `/health` and `/` are exempt (decorated with `@limiter.exempt`).
   - Rate limit exceeded returns `{"error": "Rate limit exceeded", "code": "RATE_LIMIT_EXCEEDED"}` with a `Retry-After` header.

## 🔍 Error Handling & Logging

### Structured error responses

All errors return a consistent JSON shape: `{"error": "message", "code": "ERROR_CODE", "detail": {...}}`. Custom exceptions are raised in route/service code and mapped to HTTP status codes by global handlers registered in `app/exceptions.py`. SQLAlchemy errors (integrity, data, programming) are caught and mapped automatically.

### Detail payloads

The `detail` field is optional and code-specific. Handlers populate it where a structured hint helps the client:

| Code | `detail` shape | Notes |
|---|---|---|
| `VALIDATION_ERROR` | `{"fields": [{"field": "body.email", "message": "...", "type": "..."}, ...]}` | Always present. |
| `NOT_FOUND` | `{"resource": "user_profile"}` | Only when the raiser passes `resource=`. |
| `CONFLICT` (raised) | `{"resource": "brokerage_account"}` or `{"field": "..."}` | Only when the raiser passes `resource=`/`field=`. |
| `DUPLICATE_ENTRY` / `CONFLICT` (DB) | `{"field": "email"}` | Best-effort column extraction from asyncpg (`column_name` → `Key (col)=` in `detail` → parsed `constraint_name`). Omitted when nothing can be safely extracted. |
| `INVALID_DATA` | `{"field": "..."}` | Same extraction path as above. |
| `INCOMPLETE_ONBOARDING` | `{"missing_fields": [...]}` | Populated by `IncompleteOnboardingError`. |
| `ALPACA_ERROR` | Alpaca's raw error body. | Passed through from `AlpacaBrokerError.detail`. |

Column/resource names are the only schema information ever exposed — raw SQL, constraint names, and offending values are never leaked to the client.

Custom exception classes and their HTTP status codes:

| Exception | Code | HTTP |
|-----------|------|------|
| `AuthenticationError` | `AUTHENTICATION_ERROR` | 401 |
| `AuthorizationError` | `AUTHORIZATION_ERROR` | 403 |
| `NotFoundError` | `NOT_FOUND` | 404 |
| `ConflictError` | `CONFLICT` | 409 |
| `IncompleteOnboardingError` | `INCOMPLETE_ONBOARDING` | 422 |
| `AlpacaBrokerError` | `ALPACA_ERROR` | 422 |
| `AlpacaBrokerUnavailableError` | `ALPACA_UNAVAILABLE` | 503 |

`AlpacaBrokerError` and `AlpacaBrokerUnavailableError` are defined in `app/services/alpaca_broker.py` and registered alongside the rest in `register_exception_handlers`.

### Request logging & correlation IDs

Every request is assigned a correlation ID (`X-Correlation-ID` header) by `CorrelationIDMiddleware`. If the client sends one, it's reused; otherwise a UUID is generated. The ID is:
- Stored on `request.state.correlation_id`
- Bound to structlog's contextvars — automatically included in every log call during the request
- Echoed back in the response header
- Attached to Sentry scope (when sentry-sdk is installed)

`RequestLoggingMiddleware` logs each request with method, path, status, latency, user ID, client IP, and user-agent. The correlation ID appears automatically via contextvars.

### Log output format

Logging is configured in `app/logging_config.py` using structlog:
- **Dev:** Colored console output (structlog `ConsoleRenderer`) — timestamps, logger names, IP, and user-agent are hidden for cleanliness
- **Prod/Staging:** JSON output for Railway log aggregation — all fields included for searchability

Uvicorn's built-in access log is disabled (`--no-access-log`) since the custom middleware provides richer output.

## 🗄️ Database

### Connection setup

The database is Supabase-hosted Postgres, accessed via SQLAlchemy with the asyncpg driver. The `supabase-py` SDK is NOT used for data access.

`app/database.py` creates an async engine and session factory:
- The engine connects using `DATABASE_URL` (pooled connection via Supavisor, port 6543 in production).
- Route handlers get a session via FastAPI dependency injection.

### Local Supabase setup

Local development uses the Supabase CLI to run Postgres and Auth as Docker containers. The config lives in `supabase/config.toml` (committed to git).

Key local ports (from `supabase/config.toml`):

| Service | Port |
|---------|------|
| Supabase API (PostgREST) | 54321 |
| Postgres | 54322 |
| Supabase Studio | 54323 |
| Inbucket (email testing) | 54324 |
| Analytics | 54327 |

After running `make infra` (`supabase start`), run `supabase status` to retrieve the local `SUPABASE_ANON_KEY` and other local credentials needed for `.env`.

The `supabase start` command starts all containers defined by `config.toml`. Data persists between sessions in a local Docker volume. `supabase stop` stops the containers without deleting data; `supabase db reset` wipes and reseeds from scratch.

### Dual port setup (production only)

Supabase provides two connection endpoints for the same database:

- **Port 6543 (Supavisor pooled):** Used by the running app. The connection pooler multiplexes many concurrent requests across a smaller pool of database connections. Required to avoid exhausting Postgres connection limits under load.
- **Port 5432 (direct):** Used by Alembic for migrations. DDL statements (CREATE TABLE, ALTER COLUMN) require a direct session — the pooler doesn't handle these reliably.

In Railway env vars: `DATABASE_URL` points to port 6543, `DATABASE_URL_DIRECT` points to port 5432. Alembic's `env.py` reads `DATABASE_URL_DIRECT`. Locally, both point to the same `localhost:54322` (the port Supabase CLI exposes Postgres on, as configured in `supabase/config.toml`).

### Migrations (Alembic)

SQLAlchemy models are the source of truth for the schema. Alembic generates migration files by diffing models against the current database state.

Migrations run automatically on every deploy — Railway's release command executes `alembic upgrade head` before the new app version starts serving traffic.

Migration files are committed to git in `migrations/versions/`. They contain `upgrade()` and `downgrade()` functions.

### Handling migration conflicts

Alembic migrations form a chain — each migration points to its parent. When two developers create migrations on separate branches off `main`, both point to the same parent. After both merge, Alembic sees two heads and `alembic upgrade head` fails.

**To fix:** Alembic has a merge command: `alembic merge -m "merge migrations" <head1> <head2>`. This creates a merge migration that unifies the chain. Takes seconds.

**To detect:** Run `alembic heads` — if it shows more than one head, you need to merge. CI should also check for this (the backend workflow runs `alembic heads` and fails the PR if multiple heads exist).

**In practice:** Whoever merges second is responsible for running the merge. Before merging a PR that includes a migration, pull latest `main` and check for multiple heads.

### What lives in the database vs. what doesn't

**In our database:** user profiles (name, address, citizenship, disclosures, onboarding step), financial profile (income, net worth, risk answers, employment), brokerage account record (Alpaca account ID, status, KYC results), AI conversation history, analysis results, user preferences, watchlists, notification settings.

**NOT in our database:** SSNs, government IDs, bank account numbers, portfolio positions, account balances, order history, transaction records. All live financial data is queried from Alpaca in real time. SSNs are forwarded directly to Alpaca during KYC submission and never stored.

### Row Level Security

RLS is NOT used. Since the Sevino API is the only client connecting to Postgres (not end users directly), access control is enforced in the application layer. Every query includes `WHERE user_id = <authenticated_user_id>` via SQLAlchemy.

## 📈 Alpaca Integration

Alpaca is the broker-dealer. It handles brokerage accounts, KYC verification, trade execution, custody of funds, and regulatory compliance. The user never interacts with Alpaca directly.

### Authentication with Alpaca

`AlpacaBrokerService` (in `app/services/alpaca_broker.py`) authenticates using the OAuth2 client credentials flow. On the first request (and when the cached token expires), it posts to `{ALPACA_AUTH_URL}/v1/oauth2/token` with `grant_type=client_credentials` using `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. The returned bearer token is cached in memory and attached as `Authorization: Bearer <token>` on all subsequent Alpaca requests. Token rotation is handled automatically — the service refreshes 60 seconds before expiry.

In sandbox: `ALPACA_AUTH_URL` = `https://authx.sandbox.alpaca.markets`  
In production: `ALPACA_AUTH_URL` = `https://authx.alpaca.markets`

These URLs come from computed properties on `Settings` (`config.py`) — they are not env vars.

### Account creation & KYC

1. The Sevino app collects personal info through an onboarding flow. Each screen calls `PATCH /v1/onboarding` to incrementally save data (name, DOB, address, employment, investment experience, disclosures). The SSN is collected last and is never saved.
2. On final submission, the app calls `POST /v1/onboarding/submit` with the SSN. `OnboardingService.submit_kyc` validates completeness, builds the Alpaca payload, and calls `POST /v1/accounts` via `AlpacaBrokerService`.
3. Account status: `SUBMITTED` → Alpaca runs async KYC → `APPROVED` → `ACTIVE` (or `ACTION_REQUIRED` / `REJECTED`).
4. The returned Alpaca account ID and initial status are stored in the `brokerage_accounts` table.
5. Once `ACTIVE`, the user can deposit funds and trade.

We do NOT store SSNs or any sensitive KYC data. The SSN is forwarded directly to Alpaca in the `POST /v1/onboarding/submit` request and discarded.

### Trading

Orders are submitted via Alpaca's Trading API: `POST /v1/trading/accounts/{account_id}/orders`. The API parses natural language input from the user (via the AI layer), constructs an order request, and submits it.

### Portfolio data

Alpaca is the source of truth. The API calls Alpaca on every request:
- Account info: equity, cash, buying power, daily P&L.
- Positions: current holdings, cost basis, market value, unrealized P&L.
- Portfolio history: timeseries of equity over any timeframe (for charts).
- Order history: all past orders with status, fill price, timestamps.

We do not store this data in our database. Redis is available for caching with short TTLs if performance becomes an issue.

## 📡 Real-Time Events (SSE)

The ARQ worker maintains persistent SSE connections to Alpaca's event APIs. Events update existing DB rows (not an append-only event log). The FastAPI web server never touches these connections — it just reads the DB/cache when the iOS app asks.

Alpaca's Broker API does not offer a WebSocket endpoint for trade updates (the `wss://api.alpaca.markets/stream` endpoint belongs to the Trading API and uses a different auth model); SSE is the canonical real-time channel for Broker API partners.

### Connections

Three persistent SSE connections, maintained by the ARQ worker (not the web process), regardless of how many users exist:

| # | Protocol | Endpoint | Purpose |
|---|----------|----------|---------|
| 1 | SSE | `GET /v1/events/accounts/status` | KYC lifecycle (SUBMITTED → ACTIVE, ACTION_REQUIRED, REJECTED) |
| 2 | SSE | `GET /v1/events/transfers/status` | ACH lifecycle (QUEUED → PENDING → COMPLETE, REJECTED, RETURNED) |
| 3 | SSE | `GET /v2/events/trades` | Order fills, cancels, rejects |

All Sevino users' events arrive on the same connections. Each event payload includes `account_id` to match to the right user in the database.

**Concurrency limit.** Alpaca's Broker API allows up to **25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)); past that, further connections receive `Too many requests`. See §Worker topology for how we allocate that budget across dev / staging / PR preview environments.

### How SSE works

SSE (Server-Sent Events) is a one-way streaming protocol over plain HTTP. The worker makes a `GET` request to Alpaca; Alpaca never closes the response. Instead it keeps writing text lines in a defined format:

```
event: account_status
data: {"event_id": 12627517, "event_ulid": "01HCMKXQYJ3ZBV66Q21KCT1CRR", "account_id": "abc", "status_from": "SUBMITTED", "status_to": "ACTIVE"}

event: account_status
data: {"event_id": 12627518, "event_ulid": "01HCMKXR8K3ZBV66Q21KCT4DQS", "account_id": "def", "status_from": "SUBMITTED", "status_to": "REJECTED"}
```

The connection stays open indefinitely. Each block is a discrete event pushed whenever something happens. If the connection drops, the worker reconnects with `?since_ulid=<last_ulid>` and Alpaca replays everything missed — SSE has built-in replay, so no events are lost across reconnects.

### Comment lines (heartbeats + diagnostics)

Alongside `event:` / `data:` frames, Alpaca also sends SSE comment lines (lines starting with `:`). We read and surface all of them:

| Comment | When | What we do |
|---------|------|------------|
| `:heartbeat` | On idle streams, proving the TCP connection is alive (Alpaca's FAQ: *"Alpaca would never stop responding, hence we also send 'heartbeat' to let partners know that the connection is alive"*) | Bump `last_message_received_at`, info-log `sse_benign_comment` |
| `: welcome to the Alpaca events` | Emitted once on every successful connect (observed against `/v1/events/accounts/status` in sandbox) | Bump liveness, info-log `sse_benign_comment`. **No** breadcrumb — would otherwise fire on every reconnect and bury real diagnostics |
| `: you are reading too slowly, dropped N messages` | Slow-client warning — our consumer fell behind | Bump liveness, warning log, breadcrumb, plus a standalone Sentry `capture_message` tagged with `sse_dropped_messages=N` so it's searchable independent of whether the connection later drops |
| `: internal server error` | v2/v2beta1 endpoints only — sent by Alpaca before it closes the connection | Bump liveness, warning log, Sentry breadcrumb so it attaches to the subsequent disconnect event |

`httpx_sse.aiter_sse()` silently swallows comment lines, so the listener reads raw lines via `event_source.response.aiter_lines()` and feeds non-comment lines to `httpx_sse`'s `SSEDecoder` itself. Real events flow through `handle_event` unchanged.

### Checkpoint & resume strategy

Each SSE stream's last processed event ID is stored in a Postgres table (`sse_checkpoints`): one row per stream (`stream_name` PK, `last_event_id`, `updated_at`). Updated after each event is successfully processed.

The checkpoint value is the ULID pulled from the parsed JSON payload — not the SSE wire-protocol `id:` line — so the listener is independent of whether Alpaca populates that line. Which JSON field carries the ULID depends on the endpoint: legacy endpoints expose it in `event_ulid`, already-migrated endpoints (`/v2/events/trades`, admin actions) expose it directly in `event_id`. The column is named `last_event_id` for historical reasons, but the value is always a ULID string.

| Scenario | Behavior |
|----------|----------|
| First-ever deploy | No checkpoint row → connect without resume param → stream from now |
| Worker restart / redeploy | Read `last_event_id` from Postgres → reconnect with `?since_ulid=<ulid>` (or `?since_id=<ulid>` for already-migrated endpoints) → Alpaca replays missed events |
| Checkpoint lost | Connect without resume param → stream from now; backfill gaps via Alpaca REST if needed |

No Redis is needed for checkpointing — Postgres is the durable store and it survives restarts, redeploys, and worker crashes.

### Implementing a new listener

A new listener is a subclass of `BaseSSEListener` (`app/listeners/base_sse.py`). The required surface area:

- Set `stream_name` (unique per stream; used as the `sse_checkpoints` PK and Sentry tag).
- Set `endpoint_path` (e.g. `/v1/events/accounts/status`).
- Set `silence_threshold_seconds` (the liveness cron alerts when no event has arrived within this window).
- Implement `handle_event(session, event_type, data)` — runs inside the same transaction as the checkpoint upsert, so a raise rolls back both.

The base class already owns connect/reconnect, checkpoint persistence, exponential backoff, correlation IDs, Sentry scope tagging, and liveness timestamping — subclasses should not reimplement any of that.

**Resume-param overrides.** Alpaca is migrating all SSE streams from integer `event_id` to ULIDs. The base class's defaults (`resume_field = "event_ulid"`, `resume_param = "since_ulid"`) match legacy endpoints — the ULID lives in a separate `event_ulid` JSON field and the resume query param is `since_ulid`. For already-migrated endpoints (`/v2/events/trades`, admin actions), the ULID lives directly in the `event_id` JSON field and the resume param is `since_id` (name unchanged, value is now a ULID). Those subclasses must override:

```python
class TradeEventsListener(BaseSSEListener):
    stream_name = "trade_events_sse"
    endpoint_path = "/v2/events/trades"
    silence_threshold_seconds = ...
    resume_field = "event_id"
    resume_param = "since_id"
```

Using ULIDs today — even on legacy endpoints that still accept integer `since_id` — means we won't be forced to migrate every listener in lockstep when Alpaca deprecates the integer resume params. Reference: https://docs.alpaca.markets/docs/sse-events.

### Event handlers

All handlers UPDATE existing rows, not INSERT new ones. The operation is always "find the row by Alpaca ID, update its status."

**Account status:**
1. Look up `brokerage_accounts` by `alpaca_account_id`.
2. Set `account_status` to the new value.
3. If status is `ACTIVE`: trigger FDIC sweep enrollment via Alpaca REST, set `activated_at`.
4. Invalidate relevant cache keys.

**Transfer status:**
1. Invalidate balance/account cache so the next app read sees updated funds.
2. Future: send push notification to user.

**Trade events:**
1. Look up `order_events` by `alpaca_order_id`.
2. Update `status`, `filled_avg_price`, `filled_qty`, `filled_at`.
3. Invalidate positions/account cache.

A single SSE connection per stream delivers events sequentially, so events always arrive in order and duplicates are not a concern. Handlers are UPDATE-idempotent regardless — writing the same status/fill data twice produces the same result — so replay after reconnect (via `since_ulid`) is safe.

### Worker integration

The SSE listeners run as `asyncio.Task`s spawned in the ARQ worker's `startup` hook and cancelled in `shutdown`. They are persistent loops (not cron jobs) with internal reconnection logic using exponential backoff on connection failure. A separate liveness cron reads each listener's `last_message_received_at` and alerts if it's been silent longer than `silence_threshold_seconds` (default 90s, sized to survive ~6 missed 15s heartbeats; subclasses can override per stream).

```python
async def startup(ctx: dict):
    ctx["sse_account"] = asyncio.create_task(listen_account_status(ctx))
    ctx["sse_transfer"] = asyncio.create_task(listen_transfer_status(ctx))
    ctx["sse_trade"] = asyncio.create_task(listen_trade_events(ctx))

async def shutdown(ctx: dict):
    for key in ("sse_account", "sse_transfer", "sse_trade"):
        task = ctx.get(key)
        if task:
            task.cancel()
```

The web server (FastAPI) is unaware of these connections. The iOS app calls API endpoints, which read from Postgres (and optionally Redis cache). The data is already up to date because the worker processed the events in the background.

Example flow for KYC:
1. User submits KYC → API sends `POST /v1/accounts` to Alpaca → stores `account_status = "SUBMITTED"`.
2. Alpaca runs async KYC (minutes to hours).
3. SSE pushes `{"status_to": "ACTIVE"}` → worker updates `brokerage_accounts` row.
4. User opens app → iOS calls API → reads `account_status = "ACTIVE"` → trading unlocked.

## 🏦 Plaid Integration

Plaid handles bank account linking for deposits and withdrawals.

### The flow

1. Sevino app opens Plaid Link (native LinkKit SDK) → user authenticates with their bank.
2. App receives a `public_token` → sends to the API.
3. API exchanges `public_token` for `access_token` via Plaid API.
4. API calls Plaid's `/processor/token/create` with `"processor": "alpaca"` → gets a processor token.
5. API passes processor token to Alpaca's `POST /v1/accounts/{id}/ach_relationships`.
6. Alpaca retrieves bank details from Plaid using the processor token and creates the ACH link.
7. Deposits/withdrawals are initiated via Alpaca's Transfers API: `POST /v1/accounts/{id}/transfers`.

The API handles steps 3-6. The app handles steps 1-2 (Plaid Link UI) and can trigger step 7 (deposit/withdraw requests).

## ⚙️ Background Jobs (ARQ + Redis)

### Why background jobs

Some operations are too slow for a synchronous API response: LLM inference for trade analysis (5-30 seconds), multi-step AI agent flows, pulling data from multiple sources, and scheduled tasks (e.g., daily portfolio summary notifications).

### Worker architecture

Three Railway services in the same project:

| Service | Start command | Role |
|---------|---------------|------|
| Web | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | Handles HTTP requests |
| Worker | `arq app.worker.WorkerSettings` | Processes jobs from Redis queue |
| Redis | (managed by Railway) | Message broker between web and worker |

All share the same environment variables and private networking.

### Job flow

1. User triggers an action (e.g., "analyze my portfolio") → Sevino app sends request to the API.
2. API creates a job, pushes to Redis via ARQ, responds immediately with a job ID.
3. ARQ worker picks up the job, executes it (calls Alpaca, calls LLM, etc.).
4. Worker stores the result in the database.
5. Sevino app retrieves the result (via polling, WebSocket, or push notification).

### Task definitions

Tasks are async Python functions in `app/tasks/`. They're registered in `app/worker.py` (ARQ worker settings). They have access to the same database, services, and configuration as the web app.

Current tasks:

| Task | Type | Cadence | Purpose |
|------|------|---------|---------|
| `health_ping` | cron | every 5 min | Placeholder heartbeat — remove once more real tasks exist |
| `check_listener_liveness` | cron | every 5 min | Reads `last_message_received_at` on every registered SSE listener. If any has been silent longer than its per-stream threshold, emits `sentry_sdk.capture_message(level="warning")` naming the stream. This is how we get paged when a listener silently drops (e.g., Alpaca stops sending during market hours). See §Real-Time Events for thresholds per stream. |

## 🚀 Deployment

### Hosting

The API runs on Railway. Three services in one project: web (FastAPI), worker (ARQ), Redis.

### Build system

Railway uses Nixpacks for zero-config builds. It detects `pyproject.toml`, runs `uv sync` to install dependencies, and starts the app using the `Procfile`.

```
# Procfile
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --proxy-headers --forwarded-allow-ips='*'
worker: arq app.worker.WorkerSettings
```

Each Railway service uses a different process from the Procfile.

### Deploy sequence

1. **Build:** Nixpacks detects Python, installs dependencies via `uv sync`.
2. **Release command:** `alembic upgrade head` — runs migrations before the new version serves traffic.
3. **Start:** Runs the appropriate Procfile command for each service.

### Worker topology

The `worker` Railway service is the sole host for every long-running Alpaca listener (account status SSE, transfer status SSE, trade events SSE). The `web` service never opens these connections. Listeners are spawned as `asyncio.Task`s inside the ARQ worker's `on_startup` hook and cancelled in `on_shutdown`. Liveness is surfaced via a cron task (`check_listener_liveness`) that reads each listener's `last_message_received_at` against a per-listener silence threshold and emits a Sentry `capture_message` when a stream has gone silent longer than expected. No separate health-check endpoint is needed — alerting bubbles up through Sentry.

**Deploy-time invariant: the `worker` service MUST run with `replicas=1` per environment.** Scaling any single environment's worker beyond 1 replica would double-consume events for that environment (each replica would open its own SSE connections to the same endpoints).

#### Connection budget across the fleet

Alpaca's Broker API caps us at **25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)). All non-prod environments share a single sandbox API key, so that 25-slot pool is the ceiling for simultaneous dev + staging + PR preview workers:

| Environment | Concurrent connections | Notes |
|---|---|---|
| Local dev | 3 | One per developer (currently 3 devs). Running `make worker` locally opens SSE connections to the sandbox. |
| Staging | 1 | The always-on staging worker. |
| PR previews | up to 21 | Each open PR spins up its own Railway preview with its own worker. |
| **Total** | **25** | Hard ceiling enforced by Alpaca. |

If the number of open PRs exceeds 21 at any moment, the 22nd+ preview worker will get `Too many requests` from Alpaca when trying to open its SSE streams, and its listeners will fail to start. The web service in that preview continues to work — only the real-time event pipeline is affected. Closing older PRs (or pausing preview environments) frees slots.

Production uses a separate Alpaca API key (different broker account), so it has its own independent 25-slot pool and does not compete with dev/staging/previews.

**What counts against the limit.** The documented quote is "25 connection requests" — we treat this as 25 concurrent connections per key across all SSE endpoints. If it turns out to be per-endpoint (25 per `/v1/events/accounts/status`, 25 per `/v2/events/trades`, etc.), our effective capacity is higher; if it's a rolling rate-limit on connection attempts rather than a concurrency ceiling, behavior on rapid reconnects will be different. Verify empirically before relying on headroom beyond what's documented above.

### Environments & PR previews

- `main` branch auto-deploys to **staging** on Railway.
- **Production** deployments are triggered manually from the Railway dashboard.
- PR preview environments spin up automatically off the staging environment when PRs are opened — isolated instances with unique URLs. Torn down on merge/close.
- Focused PR environments: Railway only deploys services affected by changed files. Root directory is set to `sevino-api/` so app-only PRs don't trigger API deploys.
- Watch path `/sevino-api/**` can be set as additional scoping.
- Instant rollback available via Railway dashboard.
- Railway supports auto PR environments for GitHub bots (Claude Code, Copilot, etc.).

### Railway MCP server (for Claude Code)

```bash
# Install the Railway CLI
npm install -g @railway/cli
railway login

# Add Railway MCP server to Claude Code
claude mcp add railway-mcp-server -- npx -y @railway/mcp-server
```

Enables managing Railway infrastructure through Claude Code — create projects, deploy, set env vars, check logs via natural language.

### Monorepo configuration

The monorepo has `sevino-api/` and `sevino-app/` at the root. Railway is configured with:
- **Root directory:** `sevino-api/` — Railway only builds from this folder.
- **Watch path:** `/sevino-api/**` — only changes in this directory trigger deploys.