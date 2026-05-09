# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sevino API is the FastAPI backend for an AI-native investment/brokerage app built by Sevino. It integrates with Supabase (auth + Postgres), Alpaca (trading), Plaid (banking), and ARQ/Redis (background jobs). Deployed on Railway.

## Commands

```bash
# Dependencies
uv sync

# Run dev server (requires `make infra` first)
make server                    # uvicorn with hot-reload

# Run background worker
make worker                    # arq app.worker.WorkerSettings

# Infrastructure
make infra                     # start Supabase + Redis
make down                      # stop Supabase + Redis

# Tests
make test                      # all tests
make test-unit                 # unit tests only
uv run pytest tests/integration                # integration tests only
uv run pytest tests/unit/test_foo.py           # single file
uv run pytest tests/unit/test_foo.py::test_bar # single test
uv run pytest -x                               # stop on first failure
uv run pytest -k "health"                      # filter by keyword

# Migrations (uses database_url_direct, not the pooled URL)
make migration msg="add users table"   # autogenerate new migration
make migrate                           # apply pending migrations (alembic upgrade head)
```

## Architecture

**Stack**: FastAPI + SQLAlchemy async (asyncpg) + Pydantic Settings + ARQ (Redis) + Alembic

**App layout** (`app/`):
- `main.py` — FastAPI app, middleware stack (CORS, correlation ID, request logging, API key gate, rate limiting), health endpoint, exception handler registration
- `rate_limit.py` — slowapi `Limiter` instance with Redis backend; key functions `get_user_or_ip` (default, keys by user ID or IP) and `get_remote_address` (IP-only, for unauthenticated endpoints)
- `config.py` — `Settings` (Pydantic BaseSettings) loaded from `.env`; normalizes environment names; handles asyncpg URL scheme; SSL for prod/staging. Computed properties: `alpaca_base_url` and `alpaca_auth_url` (sandbox vs prod URLs, not env vars)
- `database.py` — async engine + session factory; `get_db` dependency yields a session with auto-commit/rollback
- `lifecycle.py` — FastAPI lifespan context manager that creates/closes the ARQ Redis pool (`app.state.arq`) and initializes `AlpacaBrokerService` on `app.state.alpaca`
- `exceptions.py` — structured error responses (`error_response` helper), custom exceptions (`AuthenticationError`, `AuthorizationError`, `NotFoundError`, `ConflictError`, `IncompleteOnboardingError`), SQLAlchemy error handlers, generic catch-all. All registered via `register_exception_handlers(app)`
- `worker.py` — ARQ `WorkerSettings` with startup/shutdown hooks and cron jobs
- `models/` — SQLAlchemy ORM models inheriting from `models.base.Base`
- `routes/` — API routers (mounted in main.py); currently: `onboarding`
- `services/` — business logic / external API wrappers
- `services/alpaca_broker.py` — `AlpacaBrokerService` (OAuth2 client credentials via `authx.sandbox.alpaca.markets`); defines `AlpacaBrokerError` and `AlpacaBrokerUnavailableError`
- `services/onboarding.py` — `OnboardingService` for incremental step saves and KYC submission
- `services/portfolio.py` — `PortfolioService` (snapshot / holdings / history), `range_to_alpaca_params` mapper, Redis-cached responses (TTL 30/30/60s)
- `dependencies/portfolio.py` — `get_alpaca_account_context` gates non-`ACTIVE` accounts with `ConflictError("ACCOUNT_NOT_ACTIVE")` (409)
- `cache.py` — `cache_get_or_set(client, key, ttl, fetcher)` helper used by all portfolio reads
- `repositories/` — data access layer (`UserProfileRepository`, `FinancialProfileRepository`, `BrokerageAccountRepository`, `AssetRepository`)
- `schemas/_types.py` — `MoneyStr` / `QtyStr` / `PctStr` Pydantic aliases. Money/qty/pct fields serialize as JSON **strings** (not numbers) so iOS and Python share `Decimal` semantics across the wire. Never use plain `Decimal` on a portfolio response schema.
- `schemas/onboarding.py`, `schemas/portfolio.py` — Pydantic request/response models
- `routes/portfolio.py` — `GET /v1/portfolio/snapshot|holdings|history?range=...`
- `tasks/` — ARQ background job functions

**Migrations** (`migrations/`): Alembic with async support. `env.py` uses `database_url_direct` (not pooled). New model imports must be added to `env.py` for autogenerate to detect them.

**Key patterns**:
- DB sessions are FastAPI dependencies (`Depends(get_db)`) — auto-commit on success, rollback on exception
- ARQ pool lives on `app.state.arq`, initialized in lifespan
- Errors use the structured `error_response()` format: `{"error": str, "code": str, "detail"?: dict}`
- Raise custom exceptions (`AuthenticationError`, `NotFoundError`, `ConflictError`, `IncompleteOnboardingError`, etc.) instead of `HTTPException` — they're caught by registered handlers
- `APIKeyMiddleware` checks `X-API-Key` header on all requests except `/health`, `/docs`, `/redoc`, `/openapi.json`, and OPTIONS. Skipped entirely when `API_KEY` env var is empty (dev convenience)
- **Rate limiting** via slowapi + Redis (configured in `app/rate_limit.py`). Two tiers: authenticated routes default to `120/minute` per user; future auth endpoints (login, signup) should use `@limiter.limit("10/minute", key_func=get_remote_address)` per IP. `/health` and `/` are exempt. Rate limit exceeded returns structured `{"error": "...", "code": "RATE_LIMIT_EXCEEDED"}` with a `Retry-After` header. Limiter is disabled in tests via `limiter.enabled = False` in conftest

## Testing

- pytest with `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`)
- `tests/conftest.py` provides: `mock_db` (AsyncMock session), `mock_arq` (AsyncMock pool), `client` (httpx.AsyncClient with mocked deps), `authenticated_client` (auth dependency overridden)
- `tests/integration/conftest.py` provides: `db_session` (real Supabase Postgres with per-test rollback), `test_user` (inserts into `auth.users` + `user_profiles`), `authenticated_db_client` (real DB + mocked auth). Skipped automatically if local Postgres is unavailable.
- Tests use `app.dependency_overrides[get_db]` to inject mocks
- `tests/unit/` — isolated logic tests (no DB, no network)
- `tests/integration/` — endpoint tests via AsyncClient; unit-style integration tests use AsyncMock DB; DB-backed tests use real local Supabase Postgres
- `tests/fixtures/` — JSON mock response data

## Deployment

- **Railway** with Procfile (`web:` uvicorn, `worker:` arq)
- Release command runs `alembic upgrade head` before serving
- Monorepo scoping: watch path `/sevino-api/**`, root dir `sevino-api/`
- Dual Postgres ports in prod: pooled (6543) for app, direct (5432) for migrations
- PR preview environments enabled

## Environment Variables

All managed via Pydantic Settings from `.env`:
`ENVIRONMENT`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `REDIS_URL`, `SUPABASE_URL`, `API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `SENTRY_DSN`
