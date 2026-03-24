# Architecture

This document describes how the Saturn API works — the full stack, how services connect, how data flows, and how everything deploys.

## 📑 Table of Contents

- [🌐 System Overview](#-system-overview)
- [📁 Directory Structure](#-directory-structure)
- [🔐 Authentication](#-authentication)
  - [The flow](#the-flow)
  - [User data split](#user-data-split)
  - [API security layers](#api-security-layers)
- [🗄️ Database](#️-database)
  - [Connection setup](#connection-setup)
  - [Local Supabase setup](#local-supabase-setup)
  - [Dual port setup (production only)](#dual-port-setup-production-only)
  - [Migrations (Alembic)](#migrations-alembic)
  - [Handling migration conflicts](#handling-migration-conflicts)
  - [What lives in the database vs. what doesn't](#what-lives-in-the-database-vs-what-doesnt)
  - [Row Level Security](#row-level-security)
- [📈 Alpaca Integration](#-alpaca-integration)
  - [Account creation & KYC](#account-creation--kyc)
  - [Trading](#trading)
  - [Portfolio data](#portfolio-data)
- [🏦 Plaid Integration](#-plaid-integration)
  - [The flow](#the-flow-1)
- [⚙️ Background Jobs (ARQ + Redis)](#️-background-jobs-arq--redis)
  - [Why background jobs](#why-background-jobs)
  - [Architecture](#architecture)
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

The backend is a FastAPI application that serves as the intermediary between the Saturn iOS app and all external services. The app never talks to Alpaca, Plaid, or the database directly — everything goes through this API.

```
Saturn App (iOS)
  │
  │  HTTPS + JWT (Authorization: Bearer <token>)
  ▼
Saturn API — FastAPI (Railway)
  │
  ├──▶ Supabase Postgres     — user profiles, AI data, app state
  ├──▶ Alpaca Broker API      — accounts, KYC, trading, portfolios, custody
  ├──▶ Plaid API              — bank linking (token exchange only)
  ├──▶ LLM Provider           — AI agent inference (trade analysis, NL parsing)
  └──▶ Redis + ARQ Worker     — background job processing
```

## 📁 Directory Structure

```
saturn-api/
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
│   ├── main.py             # FastAPI app entry point, middleware, CORS
│   ├── config.py           # Pydantic Settings class (reads env vars / .env)
│   ├── database.py         # SQLAlchemy async engine, session factory
│   ├── auth.py             # get_current_user dependency (JWT verification)
│   ├── models/             # SQLAlchemy ORM models
│   │   ├── user.py         # profiles table (linked to auth.users)
│   │   ├── conversation.py # AI chat history
│   │   └── ...
│   ├── routes/             # API endpoint handlers
│   │   ├── auth.py         # signup callback, profile creation
│   │   ├── trading.py      # place/cancel orders, natural language trading
│   │   ├── portfolio.py    # positions, balances, history
│   │   ├── funding.py      # Plaid link, ACH transfers
│   │   ├── chat.py         # AI conversation endpoints
│   │   └── ...
│   ├── services/           # business logic, external API wrappers
│   │   ├── alpaca.py       # Alpaca BrokerClient wrapper
│   │   ├── plaid.py        # Plaid client wrapper
│   │   ├── ai/             # AI agent logic
│   │   └── ...
│   ├── worker.py           # ARQ worker settings and config
│   └── tasks/              # background task definitions
│       ├── analysis.py     # portfolio/trade analysis jobs
│       └── ...
└── tests/
    ├── conftest.py          # shared fixtures
    ├── unit/
    ├── integration/
    └── fixtures/
        └── mock_responses/
```

## 🔐 Authentication

Authentication uses Supabase Auth. The Saturn app handles signup/login via the `supabase-swift` SDK and receives a JWT. Every request to the API includes this token.

### The flow

1. User signs up or logs in on the Saturn app → Supabase Auth issues a JWT + refresh token.
2. The app stores tokens (Supabase SDK handles this) and attaches the JWT to every API request: `Authorization: Bearer <token>`.
3. FastAPI's `get_current_user` dependency (in `app/auth.py`) runs on every protected route:
   - Extracts the token from the header.
   - Verifies the signature using `SUPABASE_JWT_SECRET` (via PyJWT). This secret differs per environment — locally it comes from `supabase status`, in production from the Supabase dashboard.
   - Checks expiration.
   - Extracts the user ID from the `sub` claim.
4. The user ID is injected into route handlers via `current_user = Depends(get_current_user)`.
5. All database queries scope to that user ID (`WHERE user_id = ...`).

### User data split

- `auth.users` (managed by Supabase Auth) — credentials, email, auth metadata. We don't write to this directly.
- `profiles` table (our SQLAlchemy model) — app-specific data: Alpaca account ID, onboarding status, risk preferences, etc. Foreign-keyed to `auth.users.id`.

When a user signs up, a row in `profiles` is created with the same UUID, mapping the Supabase user to their Alpaca brokerage account.

### API security layers

1. **JWT authentication** (primary) — Supabase Auth tokens verified on every request.
2. **HTTPS** — Railway provides TLS automatically.
3. **API key** — static key embedded in the Saturn app, sent as `X-API-Key` header. Checked by middleware. Prevents casual abuse.
4. **Rate limiting** — per-user request limits via FastAPI middleware (e.g., `slowapi`).

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

After running `make infra` (`supabase start`), run `supabase status` to retrieve the local `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY`, and other local credentials needed for `.env`.

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

**In our database:** user profiles, Alpaca account ID mapping, AI conversation history, analysis results, user preferences, watchlists, notification settings.

**NOT in our database:** portfolio positions, account balances, order history, transaction records, SSNs, government IDs, bank account numbers. All financial data is queried from Alpaca in real time. Sensitive KYC data is passed through to Alpaca and never persisted.

### Row Level Security

RLS is NOT used. Since the Saturn API is the only client connecting to Postgres (not end users directly), access control is enforced in the application layer. Every query includes `WHERE user_id = <authenticated_user_id>` via SQLAlchemy.

## 📈 Alpaca Integration

Alpaca is the broker-dealer. It handles brokerage accounts, KYC verification, trade execution, custody of funds, and regulatory compliance. The user never interacts with Alpaca directly.

### Account creation & KYC

1. The Saturn app collects personal info through an onboarding form (name, DOB, SSN, address, employment, investment experience, disclosures).
2. The API sends this to Alpaca's `POST /v1/accounts` via `BrokerClient`.
3. Account status: `SUBMITTED` → Alpaca runs async KYC → `APPROVED` → `ACTIVE` (or `ACTION_REQUIRED` / `REJECTED`).
4. Status updates received via Alpaca's Events API (SSE).
5. The returned Alpaca account ID is stored in our `profiles` table.
6. Once `ACTIVE`, the user can deposit funds and trade.

We do NOT store SSNs or any sensitive KYC data. The API is a passthrough — collect from frontend, send to Alpaca, discard.

### Trading

Orders are submitted via Alpaca's Trading API: `POST /v1/trading/accounts/{account_id}/orders`. The API parses natural language input from the user (via the AI layer), constructs an order request, and submits it.

### Portfolio data

Alpaca is the source of truth. The API calls Alpaca on every request:
- Account info: equity, cash, buying power, daily P&L.
- Positions: current holdings, cost basis, market value, unrealized P&L.
- Portfolio history: timeseries of equity over any timeframe (for charts).
- Order history: all past orders with status, fill price, timestamps.

We do not store this data in our database. Redis is available for caching with short TTLs if performance becomes an issue.

## 🏦 Plaid Integration

Plaid handles bank account linking for deposits and withdrawals.

### The flow

1. Saturn app opens Plaid Link (native LinkKit SDK) → user authenticates with their bank.
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

### Architecture

Three Railway services in the same project:

| Service | Start command | Role |
|---------|---------------|------|
| Web | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | Handles HTTP requests |
| Worker | `arq app.worker.WorkerSettings` | Processes jobs from Redis queue |
| Redis | (managed by Railway) | Message broker between web and worker |

All share the same environment variables and private networking.

### Job flow

1. User triggers an action (e.g., "analyze my portfolio") → Saturn app sends request to the API.
2. API creates a job, pushes to Redis via ARQ, responds immediately with a job ID.
3. ARQ worker picks up the job, executes it (calls Alpaca, calls LLM, etc.).
4. Worker stores the result in the database.
5. Saturn app retrieves the result (via polling, WebSocket, or push notification).

### Task definitions

Tasks are async Python functions in `app/tasks/`. They're registered in `app/worker.py` (ARQ worker settings). They have access to the same database, services, and configuration as the web app.

## 🚀 Deployment

### Hosting

The API runs on Railway. Three services in one project: web (FastAPI), worker (ARQ), Redis.

### Build system

Railway uses Nixpacks for zero-config builds. It detects `pyproject.toml`, runs `uv sync` to install dependencies, and starts the app using the `Procfile`.

```
# Procfile
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: arq app.worker.WorkerSettings
```

Each Railway service uses a different process from the Procfile.

### Deploy sequence

1. **Build:** Nixpacks detects Python, installs dependencies via `uv sync`.
2. **Release command:** `alembic upgrade head` — runs migrations before the new version serves traffic.
3. **Start:** Runs the appropriate Procfile command for each service.

### Environments & PR previews

- `main` branch auto-deploys to production.
- PR preview environments spin up automatically when PRs are opened — isolated instances with unique URLs. Torn down on merge/close.
- Focused PR environments: Railway only deploys services affected by changed files. Root directory is set to `saturn-api/` so app-only PRs don't trigger API deploys.
- Watch path `/saturn-api/**` can be set as additional scoping.
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

The monorepo has `saturn-api/` and `saturn-app/` at the root. Railway is configured with:
- **Root directory:** `saturn-api/` — Railway only builds from this folder.
- **Watch path:** `/saturn-api/**` — only changes in this directory trigger deploys.