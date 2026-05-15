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
make test-unit      # Unit tests only (uv run pytest tests/unit tests/ai/unit)
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
- `cache.py` — `cache_get_or_set(client, key, ttl, fetcher)` helper used by portfolio routes. Redis client lives on `app.state.redis` (initialized in `lifecycle.py`). Portfolio data (snapshot/holdings/history) flows through this cache with 30–60s TTL — **never add a background job to pre-warm it**; refresh is pull-based from the client. See `docs/alpaca-integration.md` §"Portfolio Read Endpoints".
- `schemas/_types.py` — `MoneyStr` / `QtyStr` / `PctStr` Pydantic aliases. Every money / quantity / percentage field on portfolio responses serializes as a JSON **string**, not a number, so iOS and Python share the same `Decimal` semantics across the wire. Never use plain `Decimal` on a portfolio schema.

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
├── ai/unit/              # AI module unit tests (see docs/ai-v0-plan.md §5)
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

### Comments — no AI slop

**Default to writing no comments.** This codebase is authored with AI assistance, and the dominant failure mode is comment slop: restated code, task narration, banner sections, and empty docstring shells that bury the actual signal. Strip them.

A comment only earns its place when removing it would leave a future reader confused about something the code itself cannot express. Three justifications, and only three:

1. **Non-obvious WHY** — a business rule, external-system quirk, or workaround a reader cannot infer (e.g. `# Alpaca returns APPROVED before funding completes; orders would 400 until ACTIVE`).
2. **Concrete TODO/FIXME** — with a ticket reference or specific what+why. `# TODO(SEV-123): handle partial fills`, never `# TODO: clean up`.
3. **Public-contract docstring / DocC** — on a module, class, public function, or protocol whose contract is non-trivial. Private helpers whose name already states their purpose get no docstring.

Do NOT write:
- Comments that restate the next line of code (`# Check if account is active` above `if account.status == "ACTIVE":`).
- Banner / section comments inside a function (`# ---- validate input ----`, `# Step 1: fetch user`). If you need section labels, extract helpers instead.
- Narration of the current task or PR (`# Added for SEV-456`, `# New: handle cancel path`, `// Updated to use Liquid Glass`). That belongs in the commit message.
- Caller references (`# Called from worker.py`, `// Used by the onboarding flow`). They rot the moment another caller appears.
- Vacuous TODOs (`# TODO: refactor`, `// TODO: fix this later`).
- Commented-out code or modifiers. Git history is the archive.
- Auto-generated docstring shells (`"""Get the user."""` on `get_user`, `/// Returns the user.` on `func user()`).
- Signature restatement in docstrings (`:param user_id: The user_id.`, `Returns: A User object.`). Type hints already carry that.
- Multi-paragraph prose docstrings on small helpers, or bullet-list "feature descriptions" inside docstrings.

Exempt: Pydantic `Field(..., description=...)` strings (OpenAPI contract), `# noqa` / `# type: ignore` tooling directives, and SwiftUI `#Preview` blocks.

For the full pattern list and examples, see `.claude/agents/be-auditor/AGENT.md` §16 (Python) and `.claude/agents/fe-auditor/AGENT.md` §13 (Swift). When in doubt, delete the comment — the bar for keeping one is high.

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

### AI wire format (Pydantic ↔ Swift)

The discriminated unions in `sevino-api/app/ai/blocks.py` (`Block`) and `sevino-api/app/ai/transport/events.py` (`Event`) define the SSE wire format the chat-turn endpoint streams to iOS. iOS hand-mirrors them as Swift enums under `sevino-app/Sevino/Sevino/Models/Chat/` (e.g. `Block.swift`). There is no codegen and no CI check — drift silently breaks the iOS decoder at runtime.

When you add/remove a variant or change a field on either `Block` or `Event`, update the matching Swift enum in the same PR. If the Swift mirror doesn't exist yet (early in Project C), flag it in the PR description so the iOS author picks it up.

### Worktree bootstrap

New worktrees do not inherit gitignored files from the source worktree. The repo defines a root-level `.worktreeinclude` that lists the minimum set of ignored files (currently `sevino-api/.env`) required to run the backend. After `git worktree add`, run:

```
git worktreeinclude apply
```

from the new worktree to copy those files over from the source worktree. `git-worktreeinclude` is installed via `brew install satococoa/tap/git-worktreeinclude` (see `sevino-api/README.md` prerequisites). When adding a new gitignored file that downstream tooling depends on (e.g. a second `.env`, credentials file), add its path to `.worktreeinclude` — the `doc-writer` agent audits this file for drift against `.gitignore`.

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
