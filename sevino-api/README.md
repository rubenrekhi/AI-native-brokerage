# Sevino API

FastAPI backend for Sevino. Handles authentication, trading (via Alpaca), bank linking (via Plaid), AI agent orchestration, and background job processing.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (package manager)
- [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started) v2.71.1+ (local Postgres + Auth; >=2.71.1 required for JWKS asymmetric key signing)
- [Redis](https://redis.io/) — install via `brew install redis`
- [git-worktreeinclude](https://github.com/satococoa/git-worktreeinclude) — install via `brew install satococoa/tap/git-worktreeinclude`. Required for carrying `.env` into new git worktrees (see [Worktrees](#worktrees)).
- Docker (required by Supabase CLI)
- Alpaca Broker API sandbox keys ([sign up](https://broker-app.alpaca.markets/sign-up))
- Alpaca APR tier name for FDIC cash sweep enrollment. Alpaca configures this
  during partner onboarding; local cash-interest flows need the sandbox tier.
- Financial Modeling Prep API key for market data, stock cards, radar,
  digest, and asset enrichment. You can leave it blank for local work that
  does not touch those flows. The free tier is not sufficient for a cold radar
  bootstrap or ongoing full-catalog enrichment; use a paid tier if you need
  those pipelines to populate locally.
- Anthropic API key for AI chat, radar LLM picks, digest reranking, and AI
  smoke tests.
- Langfuse project keys are optional locally. Leave them empty to use the
  no-op tracing client.
- Plaid sandbox keys ([sign up](https://dashboard.plaid.com/signup))
- Supabase project ([create one](https://supabase.com/dashboard))

### First-Time Setup

```bash
# From the monorepo root
cd sevino-api

# Install dependencies (creates .venv automatically)
uv sync

# Copy environment template and fill in your keys
cp .env.example .env

# Start infrastructure (Supabase local config lives in supabase/config.toml)
# Run `supabase status` after this to confirm local services and copy local
# Supabase keys into .env / the iOS xcconfig as needed.
make infra
make migrate
make server
```

### Daily Workflow

The project includes a `Makefile` with shortcuts for everything:

```bash
# Start of day — spin up Supabase (Postgres + Auth) and Redis
make infra

# Terminal 1 — API server (hot-reload enabled)
make server

# Terminal 2 — background worker (processes ARQ jobs)
make worker

# End of day — shut down infrastructure
make down
```

You need both `make server` and `make worker` running for the full system. If you're working on routes that don't touch background jobs, you can skip the worker.

`make worker` does not hot-reload. If you change ARQ tasks, worker startup,
or shared code the worker imports, stop and restart it or you'll keep running
stale in-memory bytecode even after the server reflects your latest edits.

The API will be running at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

**Note on infrastructure lifecycle:** `supabase start` runs several Docker containers (Postgres, Auth, etc.) that use a few hundred MB of RAM. Always run `make down` when you're done. Your data persists between sessions. Redis is lightweight and essentially invisible when idle, but the Makefile stops it too for a clean slate.

### Worktrees

The repo defines a root-level [`.worktreeinclude`](../.worktreeinclude) that lists gitignored files (currently just `sevino-api/.env`) that must be copied into new git worktrees for the backend to run. After creating a worktree, copy those files over with:

```bash
git worktree add ../sevino-feature some-branch
cd ../sevino-feature
git worktreeinclude apply
```

`git worktreeinclude apply` reads `.worktreeinclude` from the source worktree and copies only matching ignored files — tracked files are never touched. Without this step, `pytest` and the dev server will fail in the new worktree because pydantic-settings can't find `.env`.

### Makefile Reference

```makefile
infra:          # Start Supabase + Redis
down:           # Stop Supabase + Redis
server:         # Run FastAPI dev server (hot-reload)
worker:         # Run ARQ background worker
test:           # Run all tests
test-unit:      # Run unit tests only
migrate:        # Apply database migrations
migration:      # Create a new migration (usage: make migration msg="add table")
digest-dry-run: # Generate digest cards for a user without writing a snapshot
```

### Running Tests

```bash
# All tests (or: make test)
uv run pytest

# Unit tests only (or: make test-unit)
uv run pytest tests/unit tests/ai/unit

# Integration tests only
uv run pytest tests/integration tests/ai/integration

# AI smoke tests (real Anthropic calls; default-skipped)
RUN_AI_SMOKE=1 uv run pytest tests/ai/smoke -v

# Live radar LLM integration test (real Anthropic call; default-skipped)
RUN_LIVE_LLM_TESTS=1 uv run pytest tests/integration/test_radar_llm_live.py -v

# Stop on first failure
uv run pytest -x

# Run tests matching a keyword
uv run pytest -k "test_trading"
```

### Database Migrations

```bash
# Create a new migration after changing SQLAlchemy models
# (or: make migration msg="description of change")
uv run alembic revision --autogenerate -m "description of change"

# Apply all pending migrations (or: make migrate)
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1
```

### Managing Dependencies

```bash
# Add a package
uv add <package-name>

# Remove a package
uv remove <package-name>

# Sync environment from lockfile (e.g., after pulling new changes)
uv sync
```

Both `pyproject.toml` and `uv.lock` are committed to git. The `.venv/` directory is gitignored.

## Deployment

Pushing to `main` auto-deploys to **staging** on Railway. Production deployments are triggered manually. See [docs/architecture.md](docs/architecture.md) for the full deployment architecture.

The deploy sequence is: build (`uv sync`) → release command (`alembic upgrade head`) → start (`uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --proxy-headers --forwarded-allow-ips='*'`).

**The `worker` Railway service MUST run with `replicas=1` per environment** — it hosts persistent Alpaca SSE listeners. Alpaca's Broker API caps us at **25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)); scaling a single environment's worker beyond 1 replica would double-consume events for that environment. Our connection budget across the fleet is: **3 local dev + 1 staging + up to 21 PR preview environments = 25**. If PR previews exceed 21 concurrent, later workers will get `Too many requests` from Alpaca and fail to start listeners. See [docs/architecture.md §Worker topology](docs/architecture.md#worker-topology) for details.

## Environment Variables

`cp .env.example .env` creates every setting consumed by `app.config.Settings`.
Keep required keys present even when intentionally blank; pydantic-settings
fails when a required setting is missing entirely. Real provider credentials
are only needed for flows that call those providers.

### Core Runtime

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `ENVIRONMENT` | App environment; normalized to `dev`, `staging`, or `prod`. Controls SSL, log format, docs exposure, CORS, and Alpaca host selection. | `dev` |
| `DATABASE_URL` | Async Postgres connection used by the running app. Hosted environments use the pooled Supavisor URL. | `postgresql+asyncpg://postgres:postgres@localhost:54322/postgres` |
| `DATABASE_URL_DIRECT` | Direct Postgres connection used by Alembic. Hosted environments use the direct DB URL. | Same as `DATABASE_URL` locally |
| `REDIS_URL` | Redis connection for ARQ jobs, rate limiting, listener state, and cache clients. Market data rewrites this URL to DB index 1 internally. | `redis://localhost:6379` |
| `SUPABASE_URL` | Supabase API URL used for JWKS JWT verification and GoTrue admin/phone flows. | `http://127.0.0.1:54321` |
| `SUPABASE_ANON_KEY` | Supabase publishable key sent as the `apikey` header for GoTrue REST calls. Also used by the iOS app. | From `supabase status` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase secret key for privileged admin operations and local seed scripts. Required outside `dev`. | From `supabase status` |
| `API_KEY` | Static `X-API-Key` gate. Not user auth; JWT still handles identity. Optional locally, required in staging/prod/PR previews. | _(empty — disabled)_ |
| `SENTRY_DSN` | Sentry error/performance telemetry. Optional locally. | _(empty — disabled)_ |
| `RAILWAY_ENVIRONMENT_NAME` | Railway-provided env name. Used to tag Sentry and detect PR previews named `sevino-pr-*`. | _(empty)_ |

### Alpaca

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `ALPACA_API_KEY` | Alpaca Broker API key. Use sandbox keys locally. | From Alpaca dashboard |
| `ALPACA_SECRET_KEY` | Alpaca Broker API secret. Use sandbox keys locally. | From Alpaca dashboard |
| `ALPACA_APR_TIER_NAME` | Alpaca FDIC cash-sweep APR tier name assigned when accounts become active. | Partner sandbox tier |
| `CASH_SWEEP_FDIC_INSURED_LIMIT` | Cash-sweep marketing/config value returned by cash-interest endpoints. | `2500000` |
| `CASH_SWEEP_PAYOUT_CADENCE` | Cash-sweep payout cadence returned by cash-interest endpoints. | `monthly` |

### Plaid

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `PLAID_CLIENT_ID` | Plaid client ID. Use sandbox locally. | From Plaid dashboard |
| `PLAID_SECRET` | Plaid secret. Use sandbox locally. | From Plaid dashboard |
| `PLAID_ENV` | Plaid environment. Code accepts `sandbox` and `production`. | `sandbox` |
| `PLAID_FERNET_KEY` | Fernet key list for encrypting Plaid access tokens at rest. First key encrypts; all keys decrypt for rotation. | Generate locally |
| `PLAID_WEBHOOK_URL` | Per-environment Plaid item webhook URL. Leave empty locally unless using a public tunnel; set to `https://<host>/v1/plaid/webhooks` in hosted envs. | _(empty)_ |

Generate a local Plaid Fernet key with:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### AI and Observability

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API key for chat turns, radar LLM picks, digest reranking, and AI smoke tests. Use a real key for AI flows. | From Anthropic Console |
| `ANTHROPIC_MODEL_MAIN` | Main chat model loaded at process startup. | `claude-sonnet-4-6` |
| `RADAR_LLM_MODEL` | Radar pick/label model loaded independently from chat. | `claude-sonnet-4-6` |
| `ANTHROPIC_ENABLE_WEB_SEARCH` | Enables Anthropic-hosted web search tool. Requires compliance review before staging/prod. | `false` |
| `ANTHROPIC_ENABLE_WEB_FETCH` | Enables Anthropic-hosted web fetch tool. Requires compliance review before staging/prod. | `false` |
| `ANTHROPIC_ENABLE_CODE_EXECUTION` | Enables Anthropic-hosted code execution tool. Requires compliance review before staging/prod. | `false` |
| `ANTHROPIC_WEB_SEARCH_MAX_USES` | Per-turn max web-search tool calls. | `5` |
| `ANTHROPIC_WEB_FETCH_MAX_USES` | Per-turn max web-fetch tool calls. | `5` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key for AI traces. Blank uses the no-op client. | _(empty)_ |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key for AI traces. Blank uses the no-op client. | _(empty)_ |
| `LANGFUSE_HOST` | Langfuse host. | `https://us.cloud.langfuse.com` |

The current AI runtime uses the Anthropic SDK directly with Langfuse tracing.
There is no LangChain or LangSmith dependency in `pyproject.toml`.

### Market Data and Radar

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `FMP_API_KEY` | Financial Modeling Prep key for quotes, fundamentals, profiles, ratios, analyst targets, earnings, news, stock cards, radar/digest enrichment, and asset sync. Blank disables market-data clients in dev. | _(empty)_ |
| `FMP_BARS_ENABLED` | Routes historical chart/bars through FMP instead of Alpaca's market-data feed. Kept as a reversible rollout flag. | `false` |

## API Key

Staging, production, and PR preview environments require an `X-API-Key` header on every request (except `/health` and `/docs`). This is a static key baked into the iOS app — it's not auth, just a lightweight gate to prevent random discovery.

**Local dev:** The key is optional. Leave `API_KEY` empty in your `.env` and the middleware is disabled entirely.

**Testing against staging or PR environments** (Swagger, curl, Postman, iOS app via TestFlight/dev builds):

1. Go to [Railway](https://railway.app) → **Sevino Backend** project → select **Staging** environment → **Sevino** service → **Variables**
2. Copy the `API_KEY` value
3. Include it as a header in your requests: `X-API-Key: <value>`

PR preview environments share the same key as staging. If you're using the Swagger docs (`/docs`), click the **Authorize** button at the top and paste the key there — all "Try it out" requests will include it automatically.

## Further Reading

- [Architecture](docs/architecture.md) — how the system works, directory structure, integrations, deployment
- [Testing](docs/testing.md) — test setup, mocking, CI/CD, what to test
