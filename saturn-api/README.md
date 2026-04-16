# Saturn API

FastAPI backend for Saturn. Handles authentication, trading (via Alpaca), bank linking (via Plaid), AI agent orchestration, and background job processing.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (package manager)
- [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started) v2.71.1+ (local Postgres + Auth; >=2.71.1 required for JWKS asymmetric key signing)
- [Redis](https://redis.io/) — install via `brew install redis`
- Docker (required by Supabase CLI)
- Alpaca Broker API sandbox keys ([sign up](https://broker-app.alpaca.markets/sign-up))
- Plaid sandbox keys ([sign up](https://dashboard.plaid.com/signup))
- Supabase project ([create one](https://supabase.com/dashboard))

### First-Time Setup

```bash
# From the monorepo root
cd saturn-api

# Install dependencies (creates .venv automatically)
uv sync

# Copy environment template and fill in your keys
cp .env.example .env

# Start infrastructure (Supabase local config lives in supabase/config.toml)
# Run `supabase status` after this to confirm local services are running
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

The API will be running at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

**Note on infrastructure lifecycle:** `supabase start` runs several Docker containers (Postgres, Auth, etc.) that use a few hundred MB of RAM. Always run `make down` when you're done. Your data persists between sessions. Redis is lightweight and essentially invisible when idle, but the Makefile stops it too for a clean slate.

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
```

### Running Tests

```bash
# All tests (or: make test)
uv run pytest

# Unit tests only (or: make test-unit)
uv run pytest tests/unit

# Integration tests only
uv run pytest tests/integration

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

## Environment Variables

| Variable | Description | Local Default |
|----------|-------------|---------------|
| `ENVIRONMENT` | App environment; normalized to `dev`, `staging`, or `prod`. Controls SSL, log format (console vs JSON), and whether `/docs` is exposed. | `dev` |
| `DATABASE_URL` | Postgres connection (pooled in prod via port 6543) | `postgresql+asyncpg://postgres:postgres@localhost:54322/postgres` |
| `DATABASE_URL_DIRECT` | Direct Postgres connection (for Alembic, port 5432 in prod) | Same as DATABASE_URL locally |
| `REDIS_URL` | Redis connection for ARQ job queue | `redis://localhost:6379` |
| `SUPABASE_URL` | Supabase API URL — used to fetch JWKS public keys for JWT verification. Production: Supabase dashboard → Settings → API → Project URL. | `http://127.0.0.1:54321` |
| `API_KEY` | Static API key checked via `X-API-Key` header — lightweight gate to prevent random API discovery (not auth). **Optional for local dev** (leave empty to disable). Required for staging/prod. Generate with `openssl rand -hex 32`. | _(empty — disabled)_ |
| `ALPACA_API_KEY` | Alpaca Broker API key (sandbox) | From Alpaca dashboard |
| `ALPACA_SECRET_KEY` | Alpaca Broker API secret (sandbox) | From Alpaca dashboard |
| `PLAID_CLIENT_ID` | Plaid client ID (sandbox) | From Plaid dashboard |
| `PLAID_SECRET` | Plaid secret key (sandbox) | From Plaid dashboard |
| `PLAID_ENV` | Plaid environment | `sandbox` |
| `SENTRY_DSN` | Sentry DSN for error tracking. Optional — Sentry is disabled when empty. | _(empty — disabled)_ |

## API Key

Staging, production, and PR preview environments require an `X-API-Key` header on every request (except `/health` and `/docs`). This is a static key baked into the iOS app — it's not auth, just a lightweight gate to prevent random discovery.

**Local dev:** The key is optional. Leave `API_KEY` empty in your `.env` and the middleware is disabled entirely.

**Testing against staging or PR environments** (Swagger, curl, Postman, iOS app via TestFlight/dev builds):

1. Go to [Railway](https://railway.app) → **Saturn Backend** project → select **Staging** environment → **Saturn** service → **Variables**
2. Copy the `API_KEY` value
3. Include it as a header in your requests: `X-API-Key: <value>`

PR preview environments share the same key as staging. If you're using the Swagger docs (`/docs`), click the **Authorize** button at the top and paste the key there — all "Try it out" requests will include it automatically.

## Further Reading

- [Architecture](docs/architecture.md) — how the system works, directory structure, integrations, deployment
- [Testing](docs/testing.md) — test setup, mocking, CI/CD, what to test