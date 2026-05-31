# Sevino Architecture

**Sevino — AI-Native Consumer Brokerage**
**MVP / Closed Beta | March 2026 | Confidential**

| | |
|---|---|
| **Platform** | iOS (Swift) + FastAPI |
| **Infrastructure** | Railway (web + worker + Redis) |
| **Database** | PostgreSQL via Supabase |
| **Brokerage** | Alpaca Securities LLC (Broker API) |
| **Bank Linking** | Plaid (Auth product, Alpaca processor) |
| **AI Provider** | Claude (Anthropic) — deferred to AI Architecture doc |

---

## Table of Contents

1. [System Overview](#1-system-overview)
   - [Architecture Principles](#11-architecture-principles)
   - [Service Map](#12-service-map)
   - [Tech Stack](#13-tech-stack)
2. [Authentication](#2-authentication)
   - [End-to-End Auth Flow](#21-end-to-end-auth-flow)
   - [iOS Auth Setup](#22-ios-auth-setup)
   - [Backend JWT Verification](#23-backend-jwt-verification)
   - [User Profile Creation](#24-user-profile-creation)
   - [API Security Layers](#25-api-security-layers)
3. [Database](#3-database)
   - [What's Stored vs. What's Not](#31-whats-stored-vs-whats-not)
   - [Base Model](#32-base-model)
   - [Table Overview](#33-table-overview)
   - [Caching Layer (Redis)](#34-caching-layer-redis)
   - [Connection Setup](#35-connection-setup)
   - [Migrations (Alembic)](#36-migrations-alembic)
4. [Alpaca Integration](#4-alpaca-integration)
   - [What Alpaca Owns](#41-what-alpaca-owns)
   - [Communication Protocols](#42-communication-protocols)
   - [Broker API Authentication](#43-broker-api-authentication)
   - [SSE Infrastructure](#44-sse-infrastructure)
   - [Key API Endpoints](#45-key-api-endpoints)
   - [Market Data](#46-market-data)
   - [Revenue Model](#47-revenue-model)
5. [Plaid Integration](#5-plaid-integration)
   - [What Plaid Owns](#51-what-plaid-owns)
   - [Token Exchange Flow](#52-token-exchange-flow)
   - [What's Stored vs. Passed Through](#53-whats-stored-vs-passed-through)
6. [Background Jobs](#6-background-jobs)
   - [Architecture](#61-architecture)
   - [Job Flow Pattern](#62-job-flow-pattern)
   - [Task Registry](#63-task-registry)
7. [Data Flows](#7-data-flows)
   - [Onboarding](#71-onboarding)
   - [Deposits & Withdrawals](#72-deposits--withdrawals)
   - [Cash Account](#73-cash-account)
   - [Trade Execution & Logging](#74-trade-execution--logging)
   - [Portfolio & Market Data](#75-portfolio--market-data)
   - [Radar Data Layer](#76-radar-data-layer)
   - [Order & Activity History](#77-order--activity-history)
   - [Conversation Persistence](#78-conversation-persistence)
8. [Deployment](#8-deployment)
   - [Railway Setup](#81-railway-setup)
   - [Build & Release](#82-build--release)
   - [Environments](#83-environments)
   - [Feature Flags](#84-feature-flags)
9. [Error Handling & Logging](#9-error-handling--logging)
   - [Error Response Format](#91-error-response-format)
   - [Correlation IDs](#92-correlation-ids)
   - [Logging](#93-logging)
   - [Monitoring (Sentry)](#94-monitoring-sentry)

---

## 1. System Overview

### 1.1 Architecture Principles

- **Alpaca is the system of record** for all brokerage data. Portfolio positions, balances, order history, and transaction records are never persisted in our database — they are fetched from Alpaca in real time (with optional Redis caching).
- **No direct client → external service calls.** The iOS app talks exclusively to the Sevino API. All Alpaca, Plaid, and database interactions are server-side.
- **Cache-first reads** for frequently accessed, slow-changing data. Redis sits between the API and Alpaca with defined TTLs per data type. When Alpaca confirms a state change via SSE (e.g., order fill, transfer completed), the corresponding cache keys are invalidated so the next read fetches fresh data from Alpaca. For ambient market data with no user-triggered event, cache expires naturally by TTL.
- **Background jobs for async work.** Anything that takes >1s or doesn't need a synchronous response (SSE event processing, transfer polling, radar refresh) runs as an ARQ task on the worker service.
- **Feature flags gate capabilities** without code deploys. Regulatory gating (ungated vs gray area vs RIA-required) is implemented as feature flags in the database.

### 1.2 Service Map

```
Sevino App (iOS / Swift)
  │
  │  HTTPS + JWT (Authorization: Bearer <token>)
  │  X-API-Key header
  ▼
Sevino API — FastAPI (Railway)
  │
  ├──▶ Supabase Postgres     — user profiles, conversations, app state, audit log
  ├──▶ Alpaca Broker API      — accounts, KYC, trading, portfolios, transfers, custody
  ├──▶ Plaid API              — bank linking (token exchange + processor token only)
  ├──▶ Redis                  — caching layer + ARQ job queue
  └──▶ ARQ Worker             — background job processing (SSE listener, scheduled tasks)
```

### 1.3 Tech Stack

**Backend (sevino-api/)**

| Layer | Technology | Notes |
|---|---|---|
| Framework | FastAPI | Async Python, auto-generated OpenAPI docs |
| Python | 3.12 | Pinned via `.python-version`, managed by uv |
| ORM | SQLAlchemy (async) + asyncpg | Async engine, session-per-request via FastAPI dependency injection |
| Migrations | Alembic | Auto-run on deploy via Railway release command |
| Background Jobs | ARQ + Redis | Async task queue, cron scheduling |
| Auth Verification | PyJWT + JWKS | Asymmetric ES256 verification against Supabase public keys |
| Rate Limiting | slowapi + Redis | Per-user and per-IP tiers |
| Logging | structlog | Colored console (dev), JSON (prod) for Railway log aggregation |
| Error Monitoring | Sentry (sentry-sdk) | Error tracking + performance monitoring |
| HTTP Client | httpx | Alpaca Broker API calls via `AlpacaBrokerService` (OAuth2 client credentials) |
| Brokerage SDK | alpaca-py | Official Alpaca SDK (available but not currently used — httpx used directly for Broker API) |
| Bank Linking SDK | plaid-python | Official Plaid API SDK |
| Config | Pydantic Settings | Reads from `.env`, validates and normalizes env vars |
| Package Manager | uv | Fast Python package manager, lockfile committed |

**iOS App (sevino-app/)**

| Layer | Technology | Notes |
|---|---|---|
| Language | Swift 5 | Xcode 16+, iOS 17+ deployment target |
| UI Framework | SwiftUI | MVVM architecture |
| Auth SDK | supabase-swift (^2.0.0) | Handles signup/login, JWT lifecycle, token refresh |
| Bank Linking SDK | Plaid LinkKit | Native iOS SDK for bank account linking |
| Networking | URLSession | Standard iOS HTTP client for Sevino API calls |
| Config | xcconfig files | Per-environment (debug/staging/release), gitignored |

**Infrastructure**

| Service | Provider | Notes |
|---|---|---|
| API Hosting | Railway | Three services: web (FastAPI), worker (ARQ), Redis |
| Database | Supabase (PostgreSQL) | Managed Postgres + Auth, local dev via Supabase CLI + Docker |
| Auth | Supabase Auth | Email/password, Apple Sign-In, Google Sign-In |
| Caching / Queue | Redis | Managed by Railway, shared by web + worker services |
| Error Monitoring | Sentry | Separate tags for `api` and `worker` processes |
| CI/CD | GitHub Actions | Separate workflows for backend and frontend, scoped by watch paths |
| Build System | Nixpacks (Railway) | Zero-config Python builds from `pyproject.toml` |

---

## 2. Authentication

Authentication is handled by Supabase Auth. The iOS app manages signup/login and token lifecycle via the `supabase-swift` SDK. The Sevino API never handles credentials directly — it only verifies the JWT that Supabase issues.

### 2.1 End-to-End Auth Flow

```
Sevino App (iOS)                    Supabase Auth                     Sevino API (FastAPI)
     │                                   │                                  │
     │  1. signUp/signIn(email, pass)    │                                  │
     │ ─────────────────────────────────▶│                                  │
     │                                   │                                  │
     │  2. JWT (access_token) +          │                                  │
     │     refresh_token                 │                                  │
     │ ◀─────────────────────────────────│                                  │
     │                                   │                                  │
     │  3. API request                   │                                  │
     │   Authorization: Bearer <jwt>     │                                  │
     │   X-API-Key: <static_key>         │                                  │
     │ ────────────────────────────────────────────────────────────────────▶│
     │                                   │                                  │
     │                                   │  4. Fetch JWKS public key        │
     │                                   │ ◀────────────────────────────────│
     │                                   │                                  │
     │                                   │  5. Return public key (cached)   │
     │                                   │ ────────────────────────────────▶│
     │                                   │                                  │
     │                                   │         6. Verify JWT signature  │
     │                                   │            Check expiration      │
     │                                   │            Extract user_id (sub) │
     │                                   │                                  │
     │  7. API response                  │                                  │
     │ ◀────────────────────────────────────────────────────────────────────│
```

**Step by step:**

1. User signs up or logs in on the iOS app. `AuthService.swift` calls `supabase.auth.signUp()` or `supabase.auth.signIn()` via the `supabase-swift` SDK. Supported methods: email/password, Apple Sign-In, Google Sign-In.

2. Supabase Auth returns a session containing an access token (JWT, 1-hour expiry) and a refresh token. The `supabase-swift` SDK stores both automatically and handles token refresh transparently — the app never manages tokens manually.

3. For every API request, `APIClient.swift` attaches two headers: the JWT as `Authorization: Bearer <token>` (retrieved from the Supabase SDK session), and the static API key as `X-API-Key`.

4. The Sevino API's `get_current_user` dependency (`app/auth.py`) extracts the JWT from the Authorization header and fetches the public key from Supabase's JWKS endpoint to verify the signature.

5. The JWKS public key is cached in memory by `PyJWKClient`. It only refetches when it encounters an unknown key ID (e.g., after a key rotation), so there's no per-request latency to Supabase.

6. The API verifies the JWT: checks the ES256 signature against the public key, validates expiration, confirms the `audience` claim is `"authenticated"`, and extracts the user ID from the `sub` claim.

7. The user ID is injected into the route handler via `Depends(get_current_user)`. All database queries scope to this user ID.

### 2.2 iOS Auth Setup

**Supabase client initialization** (`Supabase+Client.swift`):

The Supabase client is initialized once as a global using the project URL and anon key from `Config.xcconfig` (environment-specific, gitignored). These values are exposed to Swift via Info.plist build settings.

```swift
let supabase = SupabaseClient(
    supabaseURL: URL(string: AppConfig.supabaseURL)!,
    supabaseKey: AppConfig.supabaseAnonKey
)
```

**AuthService** (`AuthService.swift`):

A singleton `@Observable` class that wraps `supabase.auth` and tracks auth state. It listens to Supabase's `authStateChanges` async stream for events (`signedIn`, `signedOut`, `tokenRefreshed`, `initialSession`) and keeps `isAuthenticated` up to date. Views observe auth state through `AuthViewModel`, never through `AuthService` directly.

Key behaviors:
- `signUp(email, password)` — creates the account. In local dev, Supabase auto-confirms the email. In production, email confirmation is required (configurable in `supabase/config.toml`).
- `signIn(email, password)` — authenticates and triggers the `signedIn` event.
- `signOut()` — clears the session and triggers the `signedOut` event.
- `accessToken` — async property that returns the current JWT from the Supabase session. Used by `APIClient` to attach the token to requests. The `supabase-swift` SDK automatically refreshes the token if it's expired before returning it.

**APIClient** (`APIClient.swift`):

Every request to the Sevino API goes through `APIClient.shared`. Before sending, it calls `await AuthService.shared.accessToken` to get the current JWT and attaches it as `Authorization: Bearer <token>`. It also attaches the static API key as `X-API-Key`. Non-2xx responses are decoded as `APIError` (matching the backend's structured error format).

**Token lifecycle (handled by supabase-swift):**

- Access tokens expire after 1 hour (configurable in `supabase/config.toml` via `jwt_expiry`).
- The SDK automatically uses the refresh token to get a new access token when needed — the app doesn't need to handle 401s and retry.
- Refresh token rotation is enabled (`enable_refresh_token_rotation = true`), meaning each refresh token is single-use. A 10-second reuse interval is configured for race conditions (`refresh_token_reuse_interval = 10`).
- Sessions expire after 30 days of inactivity (default). After that, the user must log in again.

### 2.3 Backend JWT Verification

**Implementation** (`app/auth.py`):

The `get_current_user` dependency runs on every protected route. It's a FastAPI dependency injected via `Depends(get_current_user)`, which returns the user ID string on success or raises `AuthenticationError` on any failure.

```python
# Simplified — see app/auth.py for full implementation
jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")

async def get_current_user(request, credentials):
    # 1. Extract token from Authorization: Bearer <token>
    # 2. Fetch signing key from JWKS (cached in memory)
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    # 3. Verify signature, expiration, audience, and required claims
    payload = jwt.decode(token, signing_key.key, algorithms=["ES256"],
                         audience="authenticated", options={"require": ["exp", "sub"]})
    # 4. Extract user_id and store on request.state for downstream use
    user_id = payload["sub"]
    request.state.user_id = user_id
    return user_id
```

**Key details:**

- **Signing algorithm:** ES256 (ECC P-256). Supabase uses asymmetric signing — the backend only needs the public key, no shared secret. There is no `SUPABASE_JWT_SECRET` env var.
- **JWKS endpoint:** `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. Public, cacheable. Works the same locally (`http://127.0.0.1:54321`) and in production.
- **Key caching:** `PyJWKClient` caches public keys in memory. It only re-fetches when it encounters a key ID it doesn't recognize, which handles key rotation without downtime.
- **Required claims:** `exp` (expiration) and `sub` (user ID). The `audience` must be `"authenticated"` — this was a critical fix early on (adding `audience="authenticated"` to `jwt.decode()`).
- **Failure modes:** Missing header → 401. JWKS fetch failure → 401. Expired token → 401. Invalid signature → 401. Missing `sub` claim → 401. All return the structured error format: `{"error": "...", "code": "AUTHENTICATION_ERROR"}`.
- **Local dev compatibility:** The Supabase CLI (`supabase start`) exposes the same JWKS endpoint locally, so the same verification code works in both environments — just point `SUPABASE_URL` at the right host. Requires Supabase CLI v2.71.1+ for JWKS asymmetric key signing support.

### 2.4 User Profile Creation

Supabase Auth manages `auth.users` — it lives in the `auth` schema, owned entirely by Supabase's GoTrue service. We do NOT create a SQLAlchemy model for `auth.users`. Our app data lives in `user_profiles` in the `public` schema.

**Why no SQLAlchemy model for `auth.users`:**

- Alembic would try to generate migrations for it and conflict with Supabase's own migrations.
- Risk of accidentally writing to it and corrupting auth state.
- The `auth` schema can change when Supabase upgrades GoTrue — we don't want to be coupled to its internals.

**How `auth.users` connects to `user_profiles`:**

`user_profiles.id` IS `auth.users.id` — the same UUID, not a separate auto-generated ID. The column has no `default=uuid4()`. When a user signs up, Supabase creates a row in `auth.users`, and a Postgres trigger automatically creates the corresponding `user_profiles` row with that same UUID.

**The database trigger (`on_auth_user_created`):**

A Postgres trigger function fires on every `INSERT` into `auth.users` and creates a row in `public.user_profiles` with the same UUID and email. This must be created manually in the initial Alembic migration using raw SQL — it cannot be auto-generated by Alembic since it crosses schemas. The trigger ensures every authenticated user has a profile row before they make their first API call.

The trigger creates a minimal profile: just `id` (matching `auth.users.id`) and `email`. All other fields (`first_name`, `last_name`, `date_of_birth`, `onboarding_completed`, `onboarding_step`) start as null and are populated during onboarding.

**Foreign key handling:**

The foreign key `user_profiles.id → auth.users(id) ON DELETE CASCADE` is declared via raw SQL in the Alembic migration, NOT in the SQLAlchemy model. This is because the FK crosses from the `public` schema to the `auth` schema — if it were declared in SQLAlchemy, Alembic would try to manage the `auth` schema and conflict with Supabase.

**Alembic configuration:**

Alembic is configured with `include_schemas=False` in `migrations/env.py` so it only manages the `public` schema. It will never generate migrations for anything in the `auth` schema. The trigger function, trigger, and cross-schema FK are all created via `op.execute()` with raw SQL in the initial migration.

**Initial migration checklist (raw SQL, manual):**

1. Create the `user_profiles` table (Alembic auto-generates this from the SQLAlchemy model).
2. `op.execute()`: Add FK constraint `user_profiles.id → auth.users(id) ON DELETE CASCADE`.
3. `op.execute()`: Create the trigger function `on_auth_user_created()` that inserts into `user_profiles`.
4. `op.execute()`: Attach the trigger to `auth.users` — `AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION on_auth_user_created()`.

**What each table owns:**

- `auth.users` (Supabase-managed) — credentials, email, auth metadata, sign-in methods, email verification status. We read from this (e.g., `health/auth` endpoint) but never write to it directly.
- `user_profiles` (our table) — app identity: name, date of birth, onboarding state. `id = auth.users.id`.
- `user_financial_profiles` (our table) — questionnaire answers: income, net worth, risk tolerance, goals. Created during onboarding, not at signup. 1:1 with `user_profiles`.
- `user_settings` (our table) — app preferences: theme, text size, notification toggle. Created during onboarding or on first settings access. 1:1 with `user_profiles`.

**Scoping all queries to the authenticated user:**

Every database query includes `WHERE user_id = <authenticated_user_id>`. The user ID comes from the verified JWT's `sub` claim via `get_current_user`. Never trust a user-supplied ID in request bodies — always use the ID from the token. Row Level Security (RLS) is NOT used — since the Sevino API is the only client connecting to Postgres (not end users directly), access control is enforced in the application layer via SQLAlchemy.

### 2.5 API Security Layers

Four layers protect the API, each serving a different purpose:

**1. JWT Authentication (primary — identity)**

Every protected route requires a valid Supabase JWT. The `get_current_user` dependency (§2.3) verifies the token and extracts the user ID. This is the real auth — it proves who the caller is.

**2. HTTPS (transport encryption)**

All traffic is encrypted via TLS. Railway provides HTTPS automatically on all deployed services. Locally, traffic is unencrypted (HTTP to `localhost:8000`) which is fine for development.

**3. API Key (app identification — prevents casual discovery)**

A static key baked into the iOS app, sent as `X-API-Key` on every request. Checked by `APIKeyMiddleware` (`app/middleware/api_key.py`). This is NOT auth — it doesn't identify users. It's a lightweight gate that prevents someone from stumbling onto the API URL and poking around. If someone decompiles the app, they get the key, and that's fine — JWT handles real security.

Configuration:
- Checked via constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.
- Exempt paths: `/health`, `/docs`, `/redoc`, `/openapi.json`, and `OPTIONS` requests.
- Local dev: leave `API_KEY` empty in `.env` and the middleware is disabled entirely (becomes a no-op).
- Staging/prod: required. Generate with `openssl rand -hex 32`. Set in Railway env vars.
- Invalid or missing key returns `{"error": "Invalid or missing API key", "code": "FORBIDDEN"}` (HTTP 403).

**4. Rate Limiting (abuse prevention)**

Implemented via slowapi with Redis as the backend (`app/rate_limit.py`). Two tiers:

- **Authenticated routes (default):** 120 requests/minute per user. Keyed by `request.state.user_id` (set by `get_current_user`), falls back to client IP if the user ID isn't available.
- **Auth endpoints (strict):** 10 requests/minute per IP. Applied via decorator on login/signup routes to prevent brute force.
- **Exempt:** `/health` and `/` are excluded from rate limiting.
- **Non-production:** Rate limiting is disabled entirely when `ENVIRONMENT != prod` to avoid interfering with development and testing.
- **Exceeded:** Returns `{"error": "Rate limit exceeded", "code": "RATE_LIMIT_EXCEEDED"}` with a `Retry-After: 60` header (HTTP 429).

**Middleware execution order:**

Middleware runs in reverse registration order (last added = outermost). The request flows through:

```
CORS → CorrelationID → RequestLogging → APIKey → RateLimit (SlowAPI) → Route Handler
```

This means CORS headers are added first, then a correlation ID is assigned, then the request is logged, then the API key is checked, then rate limits are evaluated, and finally the route handler runs (which includes JWT verification via `get_current_user`).

---

## 3. Database

The database is PostgreSQL managed by Supabase. The `supabase-py` SDK is NOT used for data access — all queries go through SQLAlchemy with the asyncpg driver. Supabase provides the database hosting, Auth service, and local dev tooling (CLI + Docker).

### 3.1 What's Stored vs. What's Not

The core principle: Alpaca is the system of record for all financial data. We only store what Alpaca doesn't own.

**In our database (Supabase Postgres):**

| Data | Why it's stored locally |
|---|---|
| User profiles, financial questionnaire, app settings | App-specific data that Alpaca doesn't manage |
| Brokerage account ID mapping (`alpaca_account_id`) | Links our user to their Alpaca account — NOT the account data itself |
| Plaid item metadata (access tokens, institution name, mask) | Needed to manage bank links and initiate transfers. Access tokens encrypted at rest. |
| ACH relationship metadata | Maps which bank is linked to which brokerage account |
| AI conversations and messages (including tool_calls, mcp_cards as JSONB) | Chat persistence for the swipe-left history panel |
| Radar items (AI-generated + user-added, with TTL lifecycle) | Watchlist data with expiry/favorites logic that Alpaca doesn't handle |
| Order events (audit log) | Our record of what happened, synced from Alpaca SSE. Required for regulatory compliance (3-year retention) and linking trades to AI conversations. |
| Feature flags | Beta rollout control without code deploys |

**NOT in our database (fetched live from Alpaca):**

| Data | Why it's fetched live |
|---|---|
| Portfolio positions, holdings | Changes with every trade and market movement — Alpaca is source of truth |
| Account balances, equity, buying power, daily P&L | Real-time financial data, stale the moment you cache it |
| Order history and order status | Alpaca manages the full order lifecycle |
| Cash balance, interest accrued | Managed by Alpaca's cash sweep program |
| Portfolio history timeseries (for charts) | Generated by Alpaca from their trade records |
| SSNs, government IDs, bank account numbers | Sensitive KYC data passed through to Alpaca and never persisted. We are a passthrough. |

### 3.2 Base Model

All SQLAlchemy models inherit from a `TimestampMixin` (or equivalent base) that provides `created_at` and `updated_at` fields. These are auto-populated and should never be set manually in application code.

- `created_at` — set to `now()` on row creation via `server_default`.
- `updated_at` — set to `now()` on creation, then auto-updated on every `UPDATE` via a Postgres trigger function (`update_updated_at_column`). This trigger is created once in the initial migration and applied to every table that has an `updated_at` column.

Every new model should inherit from this base so the timestamps are consistent across all tables.

### 3.3 Table Overview

11 tables across 6 domains. Column-level detail lives in the [Database Schema doc](docs/database/db_schema.md) — this section covers the role of each table and how they relate.

**Users & Onboarding**

| Table | Cardinality | Purpose |
|---|---|---|
| `user_profiles` | 1 per user | Core identity + onboarding/KYC data. `id = auth.users.id`. Created automatically by the `on_auth_user_created` trigger (see §2.4). Includes contact info (phone, address), identity fields (citizenship, disclosures), compliance records (risk_disclosure_acknowledged_at, agreements_signed), and onboarding state (onboarding_step, onboarding_completed). |
| `user_financial_profiles` | 1:1 with `user_profiles` | Questionnaire answers (income, net worth, risk tolerance, goals, time horizon, experience level). Injected into AI context for personalized responses. Created during onboarding. |
| `user_settings` | 1:1 with `user_profiles` | App preferences (theme, text size, notifications, AI internet access toggle). Created during onboarding or on first settings access. |

**Brokerage & Funding**

| Table | Cardinality | Purpose |
|---|---|---|
| `brokerage_accounts` | 1:1 with `user_profiles` (at MVP) | Links a user to their Alpaca brokerage account. Stores `alpaca_account_id`, `account_status` (SUBMITTED → ACTIVE), `account_number`, `kyc_submitted_at`, `activated_at`, and `kyc_results` (JSONB). Does NOT store balances or positions. |
| `plaid_items` | 1:M with `user_profiles` | Plaid-linked bank accounts. Stores `plaid_item_id`, `plaid_access_token` (encrypted at rest), institution name, account mask. One user can link multiple banks. |
| `ach_relationships` | 1:M with `user_profiles` | ACH funding relationships linking a brokerage account to a bank. References both `brokerage_accounts` and optionally `plaid_items`. Stores `alpaca_relationship_id` and status (QUEUED → APPROVED). |

**AI Radar**

| Table | Cardinality | Purpose |
|---|---|---|
| `radar_items` | 1:M with `user_profiles` | AI-generated and user-added stock watchlist items. AI items expire after 7 days unless favorited (`is_favorited = true` sets `expires_at = null`). Includes symbol, company name, AI context blurb, relevance score, and source (`ai_generated` / `user_added`). |

**AI Conversations**

| Table | Cardinality | Purpose |
|---|---|---|
| `conversations` | 1:M with `user_profiles` | Container for chat sessions. Stores AI-generated title, preview text, and `last_message_at` (denormalized for sorting the chat history list). |
| `messages` | 1:M with `conversations` | Individual chat messages. `role` is `user` / `assistant` / `system`. `tool_calls` (JSONB) stores the tool invocations the AI made. `mcp_cards` (JSONB) stores the rendered card payloads displayed inline. |

**Trading Audit**

| Table | Cardinality | Purpose |
|---|---|---|
| `order_events` | 1:M with `user_profiles` | Trade order lifecycle tracking. Created when an order is submitted to Alpaca, updated via SSE events (see §4.3). Links to the `conversation` that initiated the trade (nullable — orders can exist without a conversation context). Stores symbol, side, order type, qty/notional, status, fill price, and timestamps. |

**Config**

| Table | Cardinality | Purpose |
|---|---|---|
| `feature_flags` | Global (not user-scoped) | Feature flag definitions for beta rollout. `key` (unique identifier) + `enabled` (on/off). Checked at runtime by the API. No code deploy needed to toggle. |

### 3.4 Caching Layer (Redis)

Redis sits between the API and Alpaca for frequently accessed data. Cache keys follow the pattern `{scope}:{entity}:{id}` (e.g., `user:{user_id}:positions`, `market:quote:{symbol}`).

**What's cached and TTLs:**

| Data | Cache Key Pattern | TTL | Invalidation |
|---|---|---|---|
| Portfolio history (charts) | `portfolio:history:{user_id}:{range}` | 60s | TTL + SSE invalidation on transfer events |
| Stock quotes (planned) | `market:quote:{symbol}` | 15s | TTL only (ambient market data) |

The portfolio cache helper is `cache_get_or_set()` in `app/cache.py` — it caches the **serialized response dict** (already transformed: decimal-as-string, summary stats computed) so a cache miss recomputation is idempotent. Malformed cache entries silently fall back to the fetcher. Redis client lives on `app.state.redis`, initialized in `app/lifecycle.py`.

**What is NOT cached (always live):**

- Portfolio **snapshot** (`/v1/portfolio/snapshot`) and **holdings** (`/v1/portfolio/holdings`) — they reflect user-mutated state (orders, cancels, fills, FDIC sweep, KYC transitions). iOS doesn't poll, so a TTL cache would only surface stale `buying_power` / `cash` immediately after a trade without absorbing any real load (SEV-626).
- Order submission, KYC/account creation, transfer initiation, and any write operation. These go directly to Alpaca every time.

**Invalidation strategy:**

Two mechanisms work together. Alpaca SSE events (see §4.3) trigger immediate cache key deletion for user-triggered state changes — a transfer event deletes every `portfolio:history:{user_id}:{range}` so the chart reflects the deposit/withdrawal on the next read. For ambient market data (quotes) where there's no user-triggered event, cache simply expires by TTL. The TTL also acts as a safety net if the SSE connection drops and an event is missed.

### 3.5 Connection Setup

`app/database.py` creates an async SQLAlchemy engine and session factory. Route handlers get a session via FastAPI dependency injection (`Depends(get_db)`). Sessions auto-commit on success and rollback on exception.

**Dual port setup (production only):**

Supabase provides two connection endpoints for the same database:

| Connection | Port | Used by | Why |
|---|---|---|---|
| Supavisor pooled | 6543 | Running app (`DATABASE_URL`) | Connection pooler multiplexes many concurrent requests across a smaller pool of DB connections. Required to avoid exhausting Postgres connection limits under load. |
| Direct | 5432 | Alembic migrations (`DATABASE_URL_DIRECT`) | DDL statements (CREATE TABLE, ALTER COLUMN) require a direct session — the pooler doesn't handle these reliably. |

Locally, both env vars point to `localhost:54322` (the port Supabase CLI exposes Postgres on, configured in `supabase/config.toml`).

**SSL:** Enabled for `prod` and `staging` environments via `get_ssl_connect_args()` in `app/config.py`. Disabled for `dev`.

**Local Supabase setup:**

`make infra` runs `supabase start`, which spins up Postgres, Auth, and other services as Docker containers. Data persists between sessions in a local Docker volume. `make down` stops containers without deleting data. `supabase db reset` wipes and reseeds from scratch.

Key local ports (from `supabase/config.toml`):

| Service | Port |
|---|---|
| Supabase API (PostgREST) | 54321 |
| Postgres | 54322 |
| Supabase Studio | 54323 |
| Inbucket (email testing) | 54324 |

### 3.6 Migrations (Alembic)

SQLAlchemy models are the source of truth for the schema. Alembic generates migration files by diffing models against the current database state.

**Workflow:**

1. Edit a SQLAlchemy model in `app/models/`.
2. Run `make migration msg="description"` — Alembic auto-generates a migration file in `migrations/versions/`.
3. Review the generated migration. For the initial migration, manually add the raw SQL for the auth trigger, FK, and `updated_at` trigger function (see §2.4).
4. Run `make migrate` — applies pending migrations (`alembic upgrade head`).
5. On deploy, Railway's release command runs `alembic upgrade head` automatically before the new version starts serving traffic.

**Important:** New model imports must be added to `migrations/env.py` for Alembic's autogenerate to detect them.

**Configuration:**

- `include_schemas=False` — Alembic only manages the `public` schema. It will never touch the `auth` schema.
- `DATABASE_URL_DIRECT` — Alembic uses the direct connection (port 5432 in prod), not the pooled one.
- Migration files are committed to git.

**Handling migration conflicts:**

When two devs create migrations on separate branches off `main`, both point to the same parent. After both merge, Alembic sees two heads and `alembic upgrade head` fails.

To fix: `alembic merge -m "merge migrations" <head1> <head2>` — creates a merge migration that unifies the chain. Whoever merges second is responsible for running the merge. CI runs `alembic heads` and fails the PR if multiple heads exist.

---

## 4. Alpaca Integration

Alpaca Securities LLC is the broker-dealer. It handles brokerage accounts, KYC/AML verification, trade execution, custody of funds, cash sweep, and regulatory compliance. The user never interacts with Alpaca directly — the Sevino API mediates all communication using Sevino's firm-level API keys.

For full endpoint-level detail, see the [Alpaca Broker API Integration Architecture](https://docs.google.com/document/d/1-QLGUONDjQgtmk-scjs59jgzM_tbln7BLfg-Hc5NPJw) doc. This section covers the architectural decisions and infrastructure requirements.

### 4.1 What Alpaca Owns

| Domain | Alpaca's Responsibility |
|---|---|
| Brokerage accounts | Account creation, KYC/AML verification, account status lifecycle |
| Custody | Holds all user funds and securities. SIPC-protected ($500K per customer, $250K cash sub-limit). |
| Trading | Order execution, settlement, fractional shares, market/limit orders |
| Portfolio data | Source of truth for positions, balances, equity, P&L, order history |
| ACH transfers | Deposit/withdrawal processing via ACH relationships |
| Cash sweep | FDIC Bank Sweep program — uninvested cash earns interest automatically |
| Market data | Real-time IEX quotes, historical bars, snapshots (included with Standard plan) |
| Regulatory compliance | FINRA member, handles all broker-dealer compliance |

### 4.2 Communication Protocols

Alpaca's Broker API offers two communication mechanisms. Sevino uses both.

**REST API (request/response):** The primary mechanism for reading data and initiating actions. Every account creation, order placement, position query, and market data lookup is a synchronous HTTP call. Used for on-demand data that doesn't require continuous updates.

**Server-Sent Events (SSE):** Server-to-server event streaming for asynchronous state changes that happen outside the request/response cycle: account approvals, transfer completions, order fills. The Sevino API opens a persistent connection and receives pushed updates. SSE supports historical replay via `since`/`since_id` parameters for reconnection without gaps.

The Alpaca Broker API does not expose a WebSocket trade-updates endpoint — that feature is Trading-API-only and uses a different auth model. For broker partners, SSE is the canonical channel for all real-time events (account status, transfer status, trade events).

**Protocol decision matrix:**

| Data Type | Protocol | Why |
|---|---|---|
| Account creation, order placement, position/balance queries, market data | REST | On-demand, request/response |
| Account status changes (KYC approval) | SSE | Async, server-pushed |
| Transfer status updates (deposit/withdrawal) | SSE | Async, server-pushed |
| Order fill/cancel/reject events | SSE | Async, server-pushed (Broker API has no WebSocket equivalent) |

### 4.3 Broker API Authentication

All Alpaca API calls use **OAuth2 Client Credentials** authentication. The backend exchanges a client ID + secret for a short-lived Bearer token (~15 min), then uses that token for all requests. Individual users do NOT have Alpaca credentials — the backend authenticates as Sevino and scopes requests to a specific `account_id`.

**Token exchange:** `POST https://authx.sandbox.alpaca.markets/v1/oauth2/token` with `grant_type=client_credentials`, `client_id`, `client_secret` (form-encoded). Returns `{"access_token": "...", "expires_in": 899}`. The token is cached on the `AlpacaBrokerService` instance (created during app lifespan, stored on `app.state.alpaca`) and auto-refreshed before expiry.

**Environment URLs:**

| Environment | Broker API Base URL | Auth Token URL |
|---|---|---|
| Sandbox | `https://broker-api.sandbox.alpaca.markets` | `https://authx.sandbox.alpaca.markets/v1/oauth2/token` |
| Production | `https://broker-api.alpaca.markets` | `https://authx.alpaca.markets/v1/oauth2/token` |

Credentials are stored as `ALPACA_API_KEY` (client ID) and `ALPACA_SECRET_KEY` (client secret) in Railway env vars. Implementation: `app/services/alpaca_broker.py`.

### 4.4 SSE Infrastructure

**This is a key infrastructure requirement.** Three persistent SSE connections are maintained by the ARQ worker (not the web process). They run as `asyncio.Task`s spawned in the worker's `on_startup` hook and cancelled in `on_shutdown`.

| SSE Stream | Endpoint | Events | Backend Action |
|---|---|---|---|
| Account status | `GET /v1/events/accounts/status` | SUBMITTED → ACTIVE, ACTION_REQUIRED, REJECTED | Update `brokerage_accounts.account_status`, trigger FDIC sweep enrollment on ACTIVE |
| Transfer status | `GET /v1/events/transfers/status` | QUEUED → PENDING → COMPLETE, REJECTED, RETURNED | Invalidate `portfolio:history:{user_id}:{range}` keys, push notification to user |
| Trade events | `GET /v2/events/trades` | Order fills, cancels, rejects | Update `order_events` status, invalidate `portfolio:history:{user_id}:{range}` keys |

Reconnection strategy: track last received event ID (ULID), reconnect with `since_ulid` / `since_id` parameter to replay missed events, exponential backoff on connection failures.

**Concurrency limit.** Alpaca's Broker API caps us at **25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)). All non-prod environments share one sandbox key, so the 25-slot pool covers dev + staging + PR previews combined. Current budget: 3 local dev + 1 staging + up to 21 PR previews = 25. See `docs/architecture.md` §Worker topology for details.

### 4.5 Key API Endpoints

Organized by domain. Full reference in the Alpaca integration doc.

**Account Management:**
- `POST /v1/accounts` — create brokerage account (KYC submission)
- `GET /v1/accounts/{id}` — account details and status
- `PATCH /v1/accounts/{id}` — update account (assign APR tier for FDIC sweep)

**Trading:**
- `POST /v1/trading/accounts/{id}/orders` — place order (market/limit, qty/notional)
- `GET /v1/trading/accounts/{id}/orders` — order history (open, closed, all)
- `GET /v1/trading/accounts/{id}/account` — account info (equity, cash, buying power, daily P&L, interest data)
- `GET /v1/trading/accounts/{id}/positions` — current holdings
- `GET /v1/trading/accounts/{id}/account/portfolio/history` — timeseries for charts

**Funding:**
- `POST /v1/accounts/{id}/ach_relationships` — create ACH link (via Plaid processor token)
- `POST /v1/accounts/{id}/transfers` — initiate deposit/withdrawal

**Market Data:**
- `GET /v2/stocks/{symbol}/snapshot` — latest price, quote, daily bar (most efficient single call for Stock Info Cards)
- `GET /v2/stocks/snapshots?symbols=X,Y,Z` — batch snapshots (used for Radar pricing)
- `GET /v2/stocks/{symbol}/bars` — historical OHLCV bars (for charts, configurable timeframe)
- `GET /v1/assets/{symbol}` — asset metadata (tradable, fractionable, exchange)
- `GET /v1/clock` — market clock (is_open, next_open, next_close)

### 4.6 Market Data

Alpaca's Standard plan (included with Broker API) provides real-time IEX data via REST and WebSocket. No separate data provider is needed for MVP.

All market data is fetched on-demand via REST when the user interacts with the app (taps Radar, asks about a stock, opens a modal). The chat-first UI means there's no always-visible ticker or live chart that requires continuous streaming.

The status bar portfolio value is the one exception — it's refreshed by the frontend via a lightweight background call to the account endpoint every 5 minutes while the app is in the foreground. This is a frontend-initiated call, not a server-side polling loop.

**Future option:** Alpaca's Market Data WebSocket (`wss://stream.data.alpaca.markets/v2/{feed}`) is available if a future feature requires continuous price streaming. Not needed for MVP.

### 4.7 Revenue Model

Sevino earns revenue through Alpaca's partner economics:

**Cash sweep spread (primary at MVP):** Alpaca's FDIC Bank Sweep program sweeps uninvested cash to partner banks that pay interest. Sevino configures a 0.10% APR partner take rate. The remaining interest passes through to the user (~3.20% APY at current rates). APR tiers are configured by Alpaca during partner onboarding and apply to all accounts.

Enrollment is automatic: when the SSE listener detects an account transition to ACTIVE, the backend patches the account to assign Sevino's preconfigured APR tier ID. Eligible cash sweeps once daily (cutoff ~11:45 AM ET). Interest compounds monthly.

**Future revenue levers:** PFOF (payment for order flow), margin interest, crypto markup — all available through Alpaca but not enabled at MVP.

---

## 5. Plaid Integration

Plaid handles bank account linking for ACH deposits and withdrawals. Sevino never sees or stores bank account numbers or routing numbers — Plaid captures credentials client-side, and Alpaca retrieves bank details directly from Plaid using a processor token.

For the full step-by-step flow with parameters and responses, see the [Plaid Link Integration Guide](https://docs.google.com/document/d/1F7ZZd8ZgS9ZMmGm3OrJ_QsWXzY1ZSK4bEvNSNkYLYUE). This section covers the architecture and data ownership.

### 5.1 What Plaid Owns

Plaid's role is narrow: bank authentication and account linking. That's it.

- **Auth product only** — captures account + routing numbers. No transaction data, no balance checks.
- **Alpaca processor integration** — enabled in the Plaid Dashboard. Allows generating processor tokens scoped specifically for Alpaca.
- **Account Select** — configured to "enabled for one account" in Plaid Dashboard, so the user picks a single bank account per link session.
- **Re-authentication** — in production, bank connections can expire. Plaid Link can be re-launched in "update mode" with the existing access_token so the user re-authenticates without creating a new connection.

### 5.2 Token Exchange Flow

Six steps across three actors. Steps 1–5 happen once per bank account. Step 6 repeats for every deposit/withdrawal.

```
iOS App                    Sevino API                   Plaid API              Alpaca API
  │                            │                           │                      │
  │  1. Request link_token     │                           │                      │
  │ ──────────────────────────▶│                           │                      │
  │                            │  POST /link/token/create  │                      │
  │                            │ ─────────────────────────▶│                      │
  │                            │         link_token        │                      │
  │        link_token          │◀─────────────────────────│                      │
  │◀──────────────────────────│                           │                      │
  │                            │                           │                      │
  │  2. Open Plaid Link (LinkKit SDK)                      │                      │
  │  User authenticates with bank ────────────────────────▶│                      │
  │        public_token + account_id                       │                      │
  │◀──────────────────────────────────────────────────────│                      │
  │                            │                           │                      │
  │  3. Send public_token      │                           │                      │
  │ ──────────────────────────▶│  POST /item/public_token/exchange                │
  │                            │ ─────────────────────────▶│                      │
  │                            │       access_token        │                      │
  │                            │◀─────────────────────────│                      │
  │                            │                           │                      │
  │                            │  4. POST /processor/token/create                 │
  │                            │     (processor: "alpaca") │                      │
  │                            │ ─────────────────────────▶│                      │
  │                            │     processor_token       │                      │
  │                            │◀─────────────────────────│                      │
  │                            │                           │                      │
  │                            │  5. POST /v1/accounts/{id}/ach_relationships     │
  │                            │     (processor_token)     │                      │
  │                            │ ────────────────────────────────────────────────▶│
  │                            │                     relationship_id              │
  │                            │◀────────────────────────────────────────────────│
  │                            │                           │                      │
  │                            │  6. POST /v1/accounts/{id}/transfers             │
  │                            │     (relationship_id, amount, direction)         │
  │                            │ ────────────────────────────────────────────────▶│
```

**The API handles steps 3–6.** The iOS app handles steps 1–2 (requesting the link token, opening the Plaid Link UI). The backend never touches bank credentials — they flow from the user's bank → Plaid → Alpaca, bypassing Sevino entirely.

### 5.3 What's Stored vs. Passed Through

| Data | Store? | Where | Notes |
|---|---|---|---|
| `access_token` | Yes | `plaid_items.plaid_access_token` (encrypted) | Needed for re-authentication and creating additional processor tokens for the same bank connection |
| `item_id` | Yes | `plaid_items.plaid_item_id` | Represents the bank connection. Needed for handling Plaid webhooks (item errors, account updates). |
| `account_id` | Yes | Alongside `plaid_items` | The specific bank account the user selected |
| Institution name, account mask | Yes | `plaid_items` | Display purposes (e.g., "Chase ••••4832") |
| `relationship_id` | Yes | `ach_relationships.alpaca_relationship_id` | Used for all future deposit/withdrawal calls to Alpaca |
| Processor token | No | — | Single-use. Already consumed by Alpaca in step 5. |
| Bank account number | No | — | Never touches our system. Flows from Plaid → Alpaca directly. |
| Routing number | No | — | Same. Never touches our system. |

---

## 6. Background Jobs

### 6.1 Architecture

Three Railway services share the same codebase, env vars, and private network:

| Service | Start Command | Role |
|---|---|---|
| Web | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | Handles HTTP requests, enqueues jobs |
| Worker | `arq app.worker.WorkerSettings` | Processes jobs from Redis queue, runs persistent listeners and cron tasks |
| Redis | Managed by Railway | Message broker (ARQ queue) + caching layer |

The worker has access to the same database, services, and configuration as the web process. Tasks are async Python functions in `app/tasks/`, registered in `app/worker.py`.

The ARQ Redis pool is initialized during FastAPI's lifespan (`app/lifecycle.py`) and available on `app.state.arq` for enqueueing jobs from route handlers.

### 6.2 Job Flow Pattern

**Standard async pattern (for on-demand tasks):**

1. API receives request → validates → enqueues job to Redis via `app.state.arq.enqueue_job()` → responds immediately with a job ID.
2. Worker picks up the job → executes (calls Alpaca, LLM, DB, etc.).
3. Worker stores the result in the database.
4. Client retrieves the result (polling, WebSocket push, or push notification — TBD per feature).

**Persistent listener pattern (for SSE):**

The SSE listeners (§4.4) are long-running tasks that start when the worker boots and run continuously. They don't follow the enqueue/dequeue pattern — they're started in the worker's `on_startup` hook and maintain persistent connections to Alpaca.

### 6.3 Task Registry

**Currently implemented:**

| Task | Schedule | What it does |
|---|---|---|
| Health ping | Every 5 minutes | Placeholder cron task. Verifies the worker is alive. |

**Planned — not yet built:**

| Task | Type | What it does | Cross-references |
|---|---|---|---|
| Alpaca SSE listener | Persistent | Listens for account status (`/v1/events/accounts/status`), transfer status (`/v2/events/funding/status`), and trade events (`/v2/events/trades`). Updates DB rows, invalidates cache, triggers FDIC enrollment on ACTIVE. | §4.4, §3.4, §7.4 |
| Radar refresh | Daily cron | AI generates new radar items per user. | §7.6 |
| Radar expiry cleanup | Daily cron | Removes expired, non-favorited radar items. | §7.6 |
| AI conversation processing | On-demand | Runs Claude with context, processes tool calls, stores response. | §7.8 |
| Conversation title generation | On-demand | AI generates summary title for a conversation. | §7.8 |

This list will grow as features are built. Each new background task should be added here with its trigger and cross-reference.

---

## 7. Data Flows

Each data flow follows a consistent structure:

1. **What it does** — one-line summary
2. **Sequence** — numbered steps showing what hits what (client → API → external service → cache/DB)
3. **Key decisions** — non-obvious architectural choices, edge cases, gotchas

Cross-references use `§` notation (e.g., "see §4.3 SSE Events Stream").

---

### 7.1 Onboarding

**What it does:** Single-session flow that collects the user's financial profile (Profile Card), creates an Alpaca brokerage account (KYC), and transitions the user to the main chat. 29 screens across two phases (~7 minutes total). For screen-by-screen detail, see the [Complete Onboarding & KYC Flow](https://docs.google.com/document/d/1zW0IEOwFl855NnroFj327r1g9ZBGe5moXb-Y4Ne8tPA) doc.

**Sequence:**

Phase 1 — Profile Card (screens 1–18, ~3 min):
1. iOS presents a scrolling chat-card UI. Each screen is a scripted AI message with a response area (not AI-generated — hardcoded for speed and consistency).
2. User progresses through: name, attribution, financial worries, goals, DOB, income, net worth, liquid net worth, income stability, time horizon, risk tolerance (2 screens combined into a risk mapping), and investment experience. Interspersed with 3 personalized reflection/motivational screens.
3. After each screen, iOS calls `PATCH /v1/onboarding` to persist that screen's data to the backend. This allows mid-flow resume if the user closes the app. The `onboarding_step` field on `user_profiles` tracks which screen the user is on.
4. Screen 17 (compounding chart bridge) uses the user's DOB to render a personalized chart showing the cost of waiting 5 years. This is the emotional conversion point.
5. Screen 18 (risk disclosure) — user acknowledges investment risk before proceeding. Timestamp saved to `risk_disclosure_acknowledged_at`.

Phase 2 — KYC / Alpaca Account Creation (screens 19–28, ~4 min):
6. Seamless visual transition — same UI style, tone shifts to practical. Collects legal name, SSN, address, citizenship, employment, funding sources, FINRA disclosures.
7. Each screen (except SSN) calls `PATCH /v1/onboarding` to persist data — same per-step pattern as Phase 1.
8. **SSN is held in the iOS app's memory only — NOT sent via PATCH.** It is transmitted directly to Alpaca via the submit endpoint and NEVER stored in our database.
9. Screen 27 — user signs Customer Agreement (revision 22.2024.08+ for FDIC eligibility), Margin Agreement, and FDIC Bank Sweep Terms.
10. Screen 28 (submit) — iOS calls `POST /v1/onboarding/submit` with only `{"tax_id": "..."}`. The backend loads all previously saved data from `user_profiles` + `user_financial_profiles`, derives Alpaca-specific field values (risk tolerance mapping matrix, income range brackets, etc.), builds the full Alpaca payload, and submits via `POST /v1/accounts`. The returned `alpaca_account_id` is stored in `brokerage_accounts`.
11. Alpaca runs async KYC → SSE listener (§4.4, not yet built) will receive status: SUBMITTED → ACTIVE (happy path), ACTION_REQUIRED, or REJECTED.
12. On ACTIVE: backend auto-enrolls in FDIC cash sweep by PATCHing the APR tier (§4.7). User is notified and can trade.
13. iOS navigates to the main chat. AI sends first greeting with portfolio context.

**API endpoints** (all require auth, prefix `/v1/onboarding`):
- `PATCH /v1/onboarding` — incremental save, called after every screen. Accepts all profile + financial + KYC fields as optional. Routes fields to `user_profiles` or `user_financial_profiles` via the repository layer.
- `POST /v1/onboarding/submit` — final KYC submission. Receives SSN, loads saved data, builds Alpaca payload, creates `brokerage_accounts` row.
- `GET /v1/onboarding/status` — returns full onboarding state + all saved data for resume.

**Key decisions:**

- Profile Card fields map to both our `user_financial_profiles` table AND Alpaca's identity object. The onboarding doc has the complete field-to-Alpaca mapping. Risk tolerance is derived from two screens combined (scenario + max drop tolerance) using a mapping matrix. All derivation logic lives in `app/services/onboarding.py`.
- `onboarding_step` on `user_profiles` tracks progress so users who abandon mid-flow can resume where they left off. Validated against an `OnboardingStep` enum in `app/schemas/onboarding.py`.
- Data is persisted per-step (not in a single submission) for crash recovery and device-switch resilience.
- Plaid bank linking is NOT part of the onboarding flow at MVP. Bank linking happens separately after the account is ACTIVE (see §7.2, §5.2). This may change in a future iteration.
- KYC approval is async — user doesn't wait. They go straight to the chat. If KYC is pending, trading-dependent features are gated until ACTIVE.
- SSE listener for KYC status updates is not yet built — `onboarding_completed` remains false after submission until this is implemented.

---

### 7.2 Deposits & Withdrawals

**What it does:** Initiates ACH transfers between the user's linked bank account and their Alpaca brokerage account, tracks the transfer lifecycle, and surfaces status to the user.

**Sequence:**

1. **Prerequisite:** User has an ACTIVE brokerage account and at least one APPROVED ACH relationship (see §5.2 for the Plaid bank linking flow).
2. User requests deposit/withdrawal from the iOS app (Settings > Funding) — specifies amount, direction, and which bank account.
3. iOS sends request to Sevino API: `POST /v1/funding/transfer` with `{amount, direction, ach_relationship_id}`.
4. API validates: brokerage account is ACTIVE, ACH relationship is APPROVED, amount > 0. For withdrawals, API checks available cash via `GET /v1/trading/accounts/{id}/account` (no withdrawing more than available).
5. API calls Alpaca: `POST /v1/accounts/{id}/transfers` with `{transfer_type: "ach", relationship_id, amount, direction: INCOMING|OUTGOING}`.
6. Alpaca returns transfer object with `status: QUEUED`. API returns status to client.
7. Transfer progresses asynchronously: QUEUED → PENDING → COMPLETE (or REJECTED/RETURNED). Status updates arrive via the SSE transfer stream (§4.4).
8. SSE worker receives COMPLETE event → invalidates the portfolio history cache (§3.4) → pushes notification to user. Snapshot + holdings are uncached, so the next read reflects the new cash balance directly from Alpaca.
9. iOS displays status and expected settlement time (1–3 business days for ACH).

**Key decisions:**

- If multiple ACH relationships exist, the user picks which bank to use. The app defaults to the most recently used.
- Pending deposits are NOT reflected in the displayed cash balance — we show what Alpaca reports, and Alpaca doesn't include pending transfers in the balance until settlement.
- Failed/returned transfers: the SSE worker logs the event, and the app surfaces a clear explanation. Common reasons: NSF (insufficient funds at the bank), account closed, ACH return.
- Deposit/withdrawal limits are Alpaca-imposed (varies by account status and history). We don't add our own limits at MVP.

---

### 7.3 Cash Account

**What it does:** Displays the user's cash balance, buying power, APY from the FDIC Bank Sweep, and accrued interest.

**Sequence:**

1. User asks about cash (via chat or Settings modal) → iOS calls Sevino API.
2. API checks Redis cache for `user:{id}:account` (60s TTL).
3. Cache miss → API calls Alpaca: `GET /v1/trading/accounts/{id}/account`.
4. Alpaca returns: `cash`, `buying_power`, `equity`, `last_equity`, and `cash_interest` object (APR tier, accrued interest details).
5. API caches response, returns to client.
6. iOS renders: cash balance, buying power, current APY (~3.20%), and accrued interest.

**Key decisions:**

- APY is NOT a static display value — it comes from the `cash_interest` object in the Alpaca account response. The rate is variable (tied to fed funds rate), so we always show the current rate from Alpaca with a disclaimer.
- Accrued interest is included in the same account endpoint response. Interest is booked to the account on the last business day of each month.
- The "cash account" is an abstraction — there's no separate cash account. It's the uninvested cash within the brokerage account that's automatically enrolled in the FDIC Bank Sweep.
- FDIC insurance coverage: up to $2.5M per customer (based on number of participating program banks). Displayed during onboarding and in Settings.

---

### 7.4 Trade Execution & Logging

**What it does:** Takes a user's trade intent, validates it, submits to Alpaca, streams real-time status updates, and logs the full order lifecycle in `order_events` for audit.

**Sequence:**

1. User expresses trade intent in chat (e.g., "Buy $200 of TSLA").
2. AI layer parses intent → structured order params: `{symbol, side, type, qty|notional, limit_price?}`.
3. API validates: account is ACTIVE and funded, symbol is tradable and fractionable (if notional), market hours check via `GET /v1/clock`.
4. If market is closed and order is `time_in_force: day`, warn user about potential price differences at open. PRD says queue with warning (FR-8.15).
5. If position would exceed 50% concentration, flag the risk but allow if user confirms (FR-8.10).
6. API returns MCP UI Trade Confirmation Card to iOS (rendered inline in chat): ticker, company name, order type, action, qty/dollar amount, estimated cost.
7. User long-presses to confirm (FR-8.4). No trade executes without this.
8. iOS sends confirmation → API creates `order_events` row with `status: pending`, `submitted_at: now()`, and `conversation_id` (links trade to the chat thread).
9. API submits to Alpaca: `POST /v1/trading/accounts/{id}/orders`.
10. Alpaca returns order object with `status: new|accepted`. API updates `order_events` with `alpaca_order_id`.
11. Trade events SSE listener (§4.4) receives fill/cancel/reject event → updates `order_events.status`, `filled_avg_price`, `filled_qty`, `filled_at`. Invalidates the portfolio history cache (§3.4); snapshot + holdings are uncached and pick up the new positions/buying_power on the next read.
12. API pushes status update to iOS → Trade Execution Card renders with fill details (FR-8.12) or error (FR-8.13).

**Logging — `order_events` table:**

Every order gets a row in `order_events` at step 8, before Alpaca is called. This ensures we have a record even if the Alpaca call fails. The row is then updated as the order progresses through its lifecycle via SSE trade events. Fields tracked: symbol, side, order_type, qty/notional, limit_price, status, filled_avg_price, filled_qty, submitted_at, filled_at, and the `conversation_id` that links back to the AI conversation that initiated the trade.

The `order_events` table is our audit log — it's the authoritative record of every trade the system has processed, retained for regulatory compliance (3-year minimum). If there's ever a discrepancy between our log and Alpaca's order history, Alpaca is the source of truth and we reconcile.

**Key decisions:**

- **Market orders** use `notional` (dollar amount) for fractional shares. Minimum $1.00. **Limit orders** use `qty`.
- `time_in_force`: `day` (default, expires at close) or `gtc` (good 'til canceled, for limit orders).
- Order types at MVP: `market` and `limit` only. No stop-loss, trailing stop, etc.
- The SSE trade events stream is the sole real-time channel for order status updates. The Broker API does not offer a WebSocket equivalent, and SSE's built-in `since_id` replay means no events are lost across reconnects.

---

### 7.5 Portfolio & Market Data

**What it does:** Retrieves and serves the user's holdings, positions, P&L, stock/ETF quotes, and portfolio history for charts. On-demand REST fetches with Redis caching.

**Status:** Portfolio surfaces (status bar pill, expanded modal, performance chart, holdings modal) are **live**. Implementation lives in `app/routes/portfolio.py` + `app/services/portfolio.py`; iOS lives under `Sevino/Models/Portfolio/`, `Sevino/Services/`, `Sevino/ViewModels/Portfolio/`. For the full contract — response shapes, decimal-as-string convention, range mapping, non-`ACTIVE` short-circuit, error mapping — see [`docs/alpaca-integration.md`](alpaca-integration.md#portfolio-read-endpoints-sevino-api) and `.context/portfolio-data/architecture.md`.

**Sequence:**

Portfolio reads come in two flavors: **uncached** (snapshot, holdings — straight to Alpaca every call) and **cached** (history — Redis read-through). Market data follows the same read-through pattern as history.

**Snapshot** (status bar pill, expanded modal hero):
1. iOS calls `GET /v1/portfolio/snapshot`.
2. API calls `GET /v1/trading/accounts/{id}/account` via `AlpacaBrokerService.get_trading_account` (no cache — every request goes to Alpaca).
3. Response: `account_status`, `currency`, `equity`, `last_equity`, `cash`, `buying_power`, `daily_change_abs`, `daily_change_pct` — money fields decimal-as-string. Non-`ACTIVE` accounts get 409 `ACCOUNT_NOT_ACTIVE` before reaching the service (see `alpaca-integration.md`).
4. Used by: status bar value + daily change (FR-9.2), AI greeting (FR-4.7), force-press modal (FR-9.4).

**Holdings** (user taps Holdings icon or asks AI):
1. iOS calls `GET /v1/portfolio/holdings`.
2. API issues concurrent `GET .../account` + `GET .../positions` (no cache), then joins with `assets.name` for company names.
3. Response: `account_status`, `currency`, `cash`, `total_market_value`, `positions[]` sorted by market value desc. Non-`ACTIVE` accounts get 409 before reaching the service.
4. Used by: Holdings modal (FR-9.6), Portfolio Summary Card (FR-5.1), AI context (FR-4.3), concentration risk check (FR-8.10).

**Portfolio History** (chart with time-range selector):
1. iOS calls `GET /v1/portfolio/history?range=1M` (any of `1D|1W|1M|3M|6M|YTD|1Y|ALL`).
2. API checks `portfolio:history:{user_id}:{range}` cache (60s TTL — pinned per range).
3. Cache miss → `GET .../account/portfolio/history` with the range mapped to `period` / `timeframe` / `start` (table in `alpaca-integration.md`).
4. Response: `range`, `timeframe`, `currency`, `base_value`, `end_value`, `gain_abs`, `gain_pct`, `points[]` (`{t, v}` with ISO-8601 UTC timestamps).
5. Used by: Performance Chart Card (FR-5.1), force-press modal chart.

**Stock Quotes** (planned; still hits Alpaca direct):
1. API checks `market:quote:{symbol}` cache (15s TTL).
2. Cache miss → `GET /v2/stocks/{symbol}/snapshot` (bundles latest trade, quote, daily bar, prev daily bar in one call).
3. Used by: Stock Info Card (FR-5.1), AI Radar Card.

**Stock Charts** (planned; user asks "show me TSLA's chart"):
1. `GET /v2/stocks/{symbol}/bars?timeframe={X}&start={Y}`.

**Batch Quotes** (Radar modal, comparison cards):
1. `GET /v2/stocks/snapshots?symbols=VTI,AAPL,MSFT,...` — single batch call for multiple symbols.

**Status Bar Background Refresh:**
The iOS app calls `GET /v1/portfolio/snapshot` to drive the status-bar pill. Triggers: view appearance, time-range change, scene-phase resume to active (5-minute staleness check), and pull-to-refresh. All refresh is frontend-initiated — the backend never polls. Each call goes straight to Alpaca (uncached), so the numbers always reflect the current account state post-trade.

**Key decisions:**

- All market data is on-demand REST, not continuous WebSocket streaming. The chat-first UI means data is behind user-initiated actions — no always-visible ticker or live chart.
- Money / qty / percentage fields are JSON **strings** end-to-end (`MoneyStr` / `QtyStr` / `PctStr` in `app/schemas/_types.py`; `@DecimalString` on iOS). Avoids float drift across the wire.
- Non-`ACTIVE` short-circuits prevent calling Alpaca for `SUBMITTED` / `APPROVAL_PENDING` / `ACTION_REQUIRED` / `REJECTED` accounts — iOS uses `account_status` to render onboarding/review copy instead of misleading `$0.00`.
- The `snapshot` endpoint is the most efficient call for Stock Info Cards — bundles everything needed in one response.
- Snapshot + holdings are uncached so they reflect post-trade state without an invalidation step; history is cached at 60s (ambient, with transfer-SSE invalidation) per SEV-626.
- Future option: Alpaca's Market Data WebSocket (`wss://stream.data.alpaca.markets/v2/{feed}`) is available if a future feature requires continuous price streaming. Not needed for MVP.

---

### 7.6 Radar Data Layer

**What it does:** Manages the AI Radar — a per-user list of stocks/ETFs with AI-generated context blurbs, 7-day TTL lifecycle, favorites persistence, and a daily refresh background job.

**Sequence:**

**Reading the Radar** (user taps Radar icon):
1. iOS calls `GET /v1/radar`.
2. API queries `radar_items WHERE user_id = {id} AND (expires_at > now() OR is_favorited = true)`.
3. API extracts all symbols from the query result → single batch call to Alpaca: `GET /v2/stocks/snapshots?symbols=VTI,AAPL,...`.
4. API merges stored metadata (context_blurb, source, is_favorited, relevance_score) with live price data (price, daily change).
5. Returns sorted: favorited items first, then by `created_at DESC`.

**Favoriting** (user taps favorite on a Radar item):
1. iOS sends `PATCH /v1/radar/{id}/favorite` with `{is_favorited: true}`.
2. API updates `radar_items`: sets `is_favorited = true`, sets `expires_at = null` (prevents expiry).
3. Unfavoriting reverses: sets `is_favorited = false`, sets `expires_at = now() + 7 days`.

**Tapping a Radar item** (user taps an item to learn more):
1. iOS navigates to the main chat → surfaces an MCP UI Radar Card with detailed stock info.
2. The user can continue the conversation about that stock, ask follow-ups, or initiate a trade.

**Daily Refresh** (ARQ cron job — see §6.3):
1. For each user with `onboarding_completed = true`:
2. Load Profile Card (`user_financial_profiles`): goals, risk tolerance, time horizon, experience level.
3. Load current positions from Alpaca (`GET /v1/trading/accounts/{id}/positions`).
4. Load existing radar items (to avoid duplicates).
5. Call Claude with profile + positions + market context → generate 3–5 relevant stocks/ETFs with context blurbs. Framing is educational/informational only (FR-7.9).
6. Insert new `radar_items` rows: `source = 'ai_generated'`, `expires_at = now() + 7 days`.
7. Delete expired, non-favorited items: `WHERE expires_at < now() AND is_favorited = false`.

**Key decisions:**

- Radar items are stored in our DB, not Alpaca's Watchlist API — we need metadata (AI blurbs, expiry timers, relevance scores) that Alpaca's schema doesn't support.
- No price data is stored in `radar_items`. Prices are always fetched live from Alpaca when the Radar modal opens.
- Relevance score is set by the AI during generation and used for sorting/filtering. The exact scoring criteria will be refined as the AI layer is built.
- Before the AI layer is built, radar can be seeded manually or with a simple algorithm (e.g., popular ETFs matching the user's goal profile).

---

### 7.7 Order & Activity History

**What it does:** Provides a read-only view of past orders, sourced from the `order_events` audit log in our database.

**Sequence:**

1. User opens order history (Settings > Accounts > Order History) → iOS calls `GET /v1/orders?status={filter}`.
2. API queries `order_events WHERE user_id = {id}`, with optional filters: status (filled, canceled, all), date range, symbol.
3. Returns sorted by `submitted_at DESC`: symbol, side, order_type, qty/notional, status, filled_avg_price, filled_at.

**How `order_events` stays in sync:**

The `order_events` table is populated at two points:
- **On submission** (step 8 of §7.4): API creates the row with `status: pending` before calling Alpaca. This ensures a record exists even if the Alpaca call fails.
- **On status update** (§4.4): The trade events SSE listener receives fill/cancel/reject events and updates the existing row with the final status, fill price, and timestamps. SSE's built-in `since_id` replay handles gaps across worker reconnects.

If there's ever a discrepancy between `order_events` and Alpaca's order history, Alpaca is the source of truth. A future reconciliation job could periodically compare and correct drift, but this isn't needed at MVP given SSE's replay guarantees.

**Key decisions:**

- We serve order history from our `order_events` table, not by calling Alpaca's `GET /v1/trading/accounts/{id}/orders` on every request. This is faster (local DB query vs external API call) and lets us link orders to conversations via `conversation_id`.
- Non-order activities (dividends, interest, transfers) are not yet in `order_events`. These come from Alpaca's `GET /v1/accounts/activities` endpoint and could be added to a future activity feed.
- Regulatory retention: `order_events` rows are never deleted. Minimum 3-year retention for compliance.

---

### 7.8 Conversation Persistence

**What it does:** Stores chat threads and messages so users can access conversation history (swipe left in the app) and resume previous conversations.

**Sequence:**

**Starting a new conversation:**
1. User opens the app → iOS calls `POST /v1/conversations`.
2. API creates a `conversations` row with `user_id`, `started_at = now()`.
3. API returns `conversation_id` to iOS.
4. AI sends a static greeting (pre-built, not AI-generated) with the user's name and portfolio status: "Good morning, Riley. Your portfolio is at $4,230, up 1.2% today."
5. Greeting is stored as the first `messages` row: `role: 'assistant'`, `content: <greeting>`.

**Sending/receiving messages:**
1. User sends a message → iOS calls `POST /v1/conversations/{id}/messages` with `{content}`.
2. API creates `messages` row: `role: 'user'`, `content: <user message>`.
3. API enqueues AI processing job (§6.3) → AI generates response with optional tool calls.
4. API creates `messages` row for the AI response: `role: 'assistant'`, `content: <response>`, `tool_calls: <JSONB of tool invocations>`, `mcp_cards: <JSONB of rendered card payloads>`.
5. API updates `conversations.last_message_at` and `conversations.preview` (first ~100 chars).

**Loading chat history (swipe left):**
1. iOS calls `GET /v1/conversations?limit=20&offset=0`.
2. API queries `conversations WHERE user_id = {id}`, ordered by `last_message_at DESC`.
3. Returns: conversation_id, title, preview, last_message_at for the list view.

**Loading a conversation's messages (user taps a thread):**
1. iOS calls `GET /v1/conversations/{id}/messages`.
2. API queries `messages WHERE conversation_id = {id}`, ordered by `created_at ASC`.
3. Returns all messages with role, content, tool_calls, and mcp_cards for re-rendering.

**AI-generated titles:**
1. After the first few exchanges in a thread, an ARQ job generates a summary title via Claude.
2. Updates `conversations.title`. Until then, the title is null and the frontend shows the preview text.

**Key decisions:**

- `tool_calls` (JSONB) stores the raw tool invocations the AI made (e.g., `get_stock_info("AAPL")`). `mcp_cards` (JSONB) stores the rendered card payloads that were displayed inline. Both are stored so conversations can be fully re-rendered from history without re-running tool calls.
- Message pagination: cursor-based using `created_at`. Load the most recent N messages first, load more on scroll-up.
- Conversations are never hard-deleted — they're retained for the audit trail (trades link to conversations via `order_events.conversation_id`). A soft-delete or archive flag can be added if needed.
- Title generation is async (background job) because it requires an LLM call and shouldn't block the conversation flow.

---

## 8. Deployment

### 8.1 Railway Setup

Three services in one Railway project, all sharing env vars and private networking:

| Service | Procfile Command | Role |
|---|---|---|
| Web | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --proxy-headers --forwarded-allow-ips='*'` | HTTP request handling |
| Worker | `arq app.worker.WorkerSettings` | Background jobs, SSE listeners, cron tasks |
| Redis | Managed by Railway | ARQ job queue + caching layer |

The `--proxy-headers` and `--forwarded-allow-ips='*'` flags are required for correct client IP handling behind Railway's reverse proxy (needed for rate limiting by IP).

### 8.2 Build & Release

Railway uses Nixpacks for zero-config builds. The sequence on every deploy:

1. **Build:** Nixpacks detects `pyproject.toml` → runs `uv sync` to install dependencies.
2. **Release command:** `alembic upgrade head` — runs migrations before the new version serves traffic. Uses `DATABASE_URL_DIRECT` (port 5432, direct connection).
3. **Start:** Runs the appropriate Procfile command for each service.

### 8.3 Environments

| Environment | Trigger | Notes |
|---|---|---|
| **Staging** | Auto-deploy on push to `main` | Mirrors production config. Used for QA and TestFlight builds. |
| **Production** | Manual deploy from Railway dashboard | Instant rollback available. |
| **PR Previews** | Auto-spin up when PRs are opened | Isolated instances with unique URLs. Share staging API key. Torn down on merge/close. |

Monorepo scoping: Railway root directory is `sevino-api/`, watch path is `/sevino-api/**`. App-only PRs don't trigger API deploys.

### 8.4 Feature Flags

The `feature_flags` table (§3.3) provides runtime feature gating without code deploys.

Feature flags are checked by the API at runtime (cached in memory or Redis with short TTL). They control: regulatory gating (ungated vs gray area vs RIA-required capabilities), beta feature rollout (enable trading for specific test users first), and kill switches (disable a feature immediately if something breaks).

To toggle a flag: update the `enabled` column in the database. No code deploy, no restart needed.

---

## 9. Error Handling & Logging

### 9.1 Error Response Format

All API errors return a consistent JSON shape:

```json
{"error": "Human-readable message", "code": "ERROR_CODE", "detail": {"fields": [...]}}
```

Custom exceptions are raised in route/service code and mapped to HTTP status codes by global handlers registered in `app/exceptions.py`:

| Exception | HTTP Status | Code |
|---|---|---|
| `AuthenticationError` | 401 | `AUTHENTICATION_ERROR` |
| `AuthorizationError` | 403 | `AUTHORIZATION_ERROR` |
| `NotFoundError` | 404 | `NOT_FOUND` |
| `RequestValidationError` | 422 | `VALIDATION_ERROR` (includes field-level detail) |
| `IntegrityError` (unique) | 409 | `DUPLICATE_ENTRY` |
| `IntegrityError` (other) | 409 | `CONFLICT` |
| `DataError` | 422 | `INVALID_DATA` |
| `RateLimitExceeded` | 429 | `RATE_LIMIT_EXCEEDED` (includes `Retry-After` header) |
| `Exception` (catch-all) | 500 | `INTERNAL_ERROR` (never leaks internal details) |

SQLAlchemy errors (integrity, data, programming) are caught and mapped automatically. The generic catch-all ensures no unhandled exception ever returns a raw stack trace.

**`detail` payloads by code:**

| Code | `detail` |
|---|---|
| `VALIDATION_ERROR` | `{"fields": [{"field", "message", "type"}, ...]}` |
| `NOT_FOUND` | `{"resource": "<name>"}` when `NotFoundError(resource=...)` is raised |
| `CONFLICT` (raised) | `{"resource": "<name>"}` / `{"field": "<name>"}` when passed |
| `DUPLICATE_ENTRY` / `CONFLICT` (DB) | `{"field": "<column>"}` extracted from asyncpg (`column_name` → `Key (col)=` → `constraint_name`); omitted on failure |
| `INVALID_DATA` | `{"field": "<column>"}` (same extraction) |
| `INCOMPLETE_ONBOARDING` | `{"missing_fields": [...]}` |
| `ALPACA_ERROR` | Alpaca's raw error body |

Only column/resource names are ever surfaced — raw SQL, table names, and values are never leaked.

### 9.2 Correlation IDs

Every request is assigned a correlation ID for end-to-end tracing. Implemented by `CorrelationIDMiddleware` (`app/middleware/correlation.py`).

- If the client sends `X-Correlation-ID`, it's reused. Otherwise, a UUID4 is generated.
- Stored on `request.state.correlation_id`.
- Bound to structlog's contextvars — automatically included in every log line during the request lifecycle.
- Echoed back in the response header.
- Attached to the Sentry scope (when sentry-sdk is installed) so errors can be traced to the originating request.

### 9.3 Logging

Configured in `app/logging_config.py` using structlog.

**Dev environment:** Colored console output via `ConsoleRenderer`. Timestamps, logger names, IP, and user-agent are hidden for cleanliness. HTTP status codes are color-coded (green < 300, yellow < 400, red >= 400).

**Prod/Staging:** JSON output for Railway log aggregation. All fields included for searchability.

**Request logging:** `RequestLoggingMiddleware` logs every request with: HTTP method, path, status code, latency (ms), user ID (or "anonymous"), client IP, and user-agent. The correlation ID appears automatically via structlog contextvars.

Uvicorn's built-in access log is disabled (`--no-access-log`) since the custom middleware provides richer output.

### 9.4 Monitoring (Sentry)

Sentry SDK is initialized in both the web process (`app/main.py`) and the worker process (`app/worker.py`), each tagged with `process: api` or `process: worker` for filtering.

Configuration: `traces_sample_rate=0.1` (10% of transactions sampled for performance monitoring), `send_default_pii=False` (no personally identifiable information sent to Sentry). The DSN is optional — leave `SENTRY_DSN` empty in `.env` for local dev and Sentry won't initialize.
