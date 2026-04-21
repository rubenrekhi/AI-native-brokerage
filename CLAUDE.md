# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Sevino is an AI-native brokerage app. This monorepo contains:
- **sevino-api/** — FastAPI backend (Python 3.12, deployed on Railway)
- **sevino-app/** — iOS app (Swift/SwiftUI, Xcode 16+, iOS 17+)

## Common Commands

All commands run from `sevino-api/`:

```bash
# Infrastructure
make infra          # Start Supabase + Redis (run once per session)
make down           # Stop Supabase + Redis

# Development (two terminals)
make server         # FastAPI with hot-reload (uvicorn)
make worker         # ARQ background worker

# Testing
make test           # All tests (uv run pytest)
make test-unit      # Unit tests only (uv run pytest tests/unit)
uv run pytest -x    # Stop on first failure
uv run pytest -k "test_health"  # Run tests matching keyword
uv run pytest tests/integration/test_health.py::test_health_ok  # Single test

# Database migrations
make migrate                          # Apply migrations (alembic upgrade head)
make migration msg="add users table"  # Create new migration (autogenerate)

# Dependencies
uv add <package>      # Add dependency
uv add --dev <package>  # Add dev dependency
uv sync               # Install from lock file
```

## Architecture

```
iOS App → FastAPI (Railway) → Supabase Postgres (async SQLAlchemy + Alembic)
                            → Alpaca Broker API (accounts, KYC, trading)
                            → Plaid API (bank linking)
                            → Redis + ARQ (background jobs)
```

### Backend structure (`sevino-api/app/`)

- `main.py` — FastAPI app creation, middleware stack (CORS, correlation ID, request logging, API key gate, rate limiting), root + health endpoints
- `rate_limit.py` — slowapi `Limiter` with Redis backend; two tiers: `120/minute` per user (default), `10/minute` per IP (for auth endpoints via decorator)
- `config.py` — Pydantic Settings loading env vars; normalizes `environment` to `dev`/`staging`/`prod`
- `database.py` — Async SQLAlchemy engine + session factory; `get_db` dependency
- `lifecycle.py` — FastAPI lifespan (startup/shutdown, ARQ pool init, `AlpacaBrokerService` init on `app.state.alpaca`)
- `exceptions.py` — Custom exceptions (`AuthenticationError`, `AuthorizationError`, `NotFoundError`, `ConflictError`, `IncompleteOnboardingError`, `AlpacaBrokerError`, `AlpacaBrokerUnavailableError`) + global handlers including SQLAlchemy error mapping. Use `raise NotFoundError(...)` etc. instead of `HTTPException`
- `models/` — SQLAlchemy models (DeclarativeBase in `base.py`)
- `routes/` — API route modules (included via `app.include_router`)
- `services/` — Business logic and external API wrappers
- `services/alpaca_broker.py` — `AlpacaBrokerService` using OAuth2 client credentials flow (via `authx.sandbox.alpaca.markets`); also defines `AlpacaBrokerError` and `AlpacaBrokerUnavailableError`
- `services/onboarding.py` — `OnboardingService` orchestrates per-step saves and KYC submission to Alpaca
- `repositories/` — Data access layer (`UserProfileRepository`, `FinancialProfileRepository`, `BrokerageAccountRepository`)
- `schemas/onboarding.py` — Pydantic request/response models for onboarding endpoints
- `tasks/` — ARQ background job definitions
- `worker.py` — ARQ worker settings and cron job registration

### Error handling pattern

Raise domain exceptions directly — global handlers convert them to structured JSON:
```python
raise NotFoundError("Account not found")  # → 422/401/403/404/409/500 JSON
```

Response shape: `{"error": "message", "code": "NOT_FOUND", "detail": {...}}`

### Testing structure

```
tests/
├── conftest.py           # Shared fixtures (mock_db, mock_arq, async client)
├── unit/                 # No DB or network
├── integration/          # Real test DB, mocked external services
└── fixtures/mock_responses/  # JSON matching Alpaca/Plaid response shapes
```

- pytest-asyncio with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed)
- External services mocked via `conftest.py` fixtures overriding FastAPI dependencies

## Conventions

### Commits

Conventional commits: `<type>(<scope>): <summary>`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
- Scope: 1-3 words, snakecase (e.g., `auth`, `trading_routes`)
- Summary: imperative, under 72 chars, no period
- Reference Linear tickets in body: `Refs: SEV-42`

### PRs

Use the template in `.github/PULL_REQUEST_TEMPLATE.md` with emoji headers. Each PR should be a single logical change. The PR description should cover the branch's net change, not individual commits.

### Deployment

- Railway auto-deploys `main` to staging; production deployments are triggered manually
- PRs get automatic preview environments (spun off staging)
- Release phase runs `alembic upgrade head` before serving
- Two Railway services: `web` (uvicorn) and `worker` (arq)
- Verify no multiple Alembic heads before merging: `uv run alembic heads`

### Database

- Connection strings auto-converted from `postgresql://` to `postgresql+asyncpg://`
- SSL enabled for prod/staging, disabled for dev
- Supabase local dev: Postgres on port 54322, Studio on 54323

### Worktree cleanup after read-only agents

When you spawn an agent with `isolation: "worktree"` purely for review (e.g. `be-auditor`, `fe-auditor`), the harness preserves the worktree and its `worktree-agent-<id>` scratch branch if the agent ran any git command that moved HEAD — even though no files were modified.

These agents end their final report with an explicit signal:
- `Worktree status: clean — safe to remove` → clean up immediately.
- `Worktree status: DIRTY — <reason>` → investigate before removing.

On a clean signal, run:

```
git worktree remove -f .claude/worktrees/agent-<id>
git branch -D worktree-agent-<id>
```

(`-f` is needed because the harness locks active worktrees.) Do this as soon as you've consumed the agent's report — don't let orphan worktrees accumulate.
