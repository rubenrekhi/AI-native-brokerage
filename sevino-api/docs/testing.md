# Testing

This document covers how to write and run tests for the Sevino API.

## Stack

- **pytest** — test framework
- **httpx** — async test client for FastAPI endpoints
- **pytest-mock** — mocking external services
- **pytest-asyncio** — async test support

## Test Structure

```
tests/
├── conftest.py              # shared fixtures (mock_db, mock_arq, client, authenticated_client)
├── integration/
│   ├── conftest.py          # real Supabase Postgres fixtures (db_session, test_user, authenticated_db_client)
│   ├── test_auth.py
│   ├── test_error_handling.py
│   ├── test_health.py
│   ├── test_middleware.py
│   ├── test_onboarding.py
│   └── test_rate_limit.py
├── unit/                    # isolated business logic tests (no DB, no network)
│   ├── test_auth.py
│   ├── test_config.py
│   ├── test_exceptions.py
│   ├── test_middleware.py
│   └── test_onboarding_service.py
└── fixtures/
    └── mock_responses/      # JSON fixtures for Alpaca/Plaid mock data
```

## Unit Tests

Test individual functions and business logic in isolation. No external services, no database. These run in milliseconds.

Examples of what to unit test:
- Natural language trade intent parsing ("buy 10 shares of AAPL" → structured order object).
- Portfolio data formatting and calculations.
- Input validation and error handling logic.
- Any pure business logic in `app/services/`.

## Integration Tests

Test API endpoints end to end including database interactions. Uses FastAPI's async test client (`httpx.AsyncClient`) to call endpoints programmatically and assert on responses.

All external services (Alpaca, Plaid, LLM) are mocked — integration tests verify that our API handles requests correctly and talks to the database properly, not that Alpaca's API works.

## Mocking External Services

External APIs are never called in automated tests. Use `pytest-mock` to replace service clients with fakes that return predetermined responses.

### Pattern

Each external service has a wrapper in `app/services/` (e.g., `alpaca_broker.py`, `onboarding.py`). In tests, these wrappers are replaced with mocks by patching the service class or overriding FastAPI dependencies in `conftest.py`.

Mock response data lives in `tests/fixtures/mock_responses/` as JSON files — actual response shapes copied from Alpaca/Plaid sandbox environments. This ensures mocks match real API behavior.

### What to mock

- **`AlpacaBrokerService`** (`app/services/alpaca_broker.py`) — account creation, KYC status, account retrieval. The service is available via `app.state.alpaca`; in tests, patch `request.app.state.alpaca` or override the `get_alpaca` dependency.
- **Plaid client** — token exchange, processor token creation.
- **LLM provider** — AI agent inference responses.
- **Redis/ARQ** — job enqueueing (verify jobs are created with correct parameters without actually processing them).

## Test Database

### Setup

Integration tests that hit the database run against the real local Supabase Postgres instance started by `make infra`. Tests are skipped automatically when Postgres is unavailable (no Docker running).

The DB fixtures live in `tests/integration/conftest.py`:

- **`db_session`** — creates an `AsyncSession` connected directly to `localhost:54322`, overrides the `get_db` FastAPI dependency for the duration of the test, and rolls back all writes after each test. Flushed data is visible within the same session, so assertions can query the DB.
- **`test_user`** — inserts a row into `auth.users` and `user_profiles` (mimicking the Supabase trigger) using `ON CONFLICT DO NOTHING`. Rolls back with `db_session`.
- **`authenticated_db_client`** — `httpx.AsyncClient` with real DB session and mocked auth (`get_current_user` returns the test user's ID).

The top-level `tests/conftest.py` provides mocked (non-DB) fixtures:

- **`mock_db`** — `AsyncMock` SQLAlchemy session.
- **`mock_arq`** — `AsyncMock` ARQ pool.
- **`client`** — `httpx.AsyncClient` with `mock_db` and `mock_arq` injected.
- **`authenticated_client`** — same as `client` but also overrides `get_current_user` with a fixed test user ID.

### Note on Supabase's pgTAP

Supabase includes pgTAP for database-level unit testing (RLS policies, schemas, triggers). We don't use it because our business logic lives in Python/SQLAlchemy (not Postgres functions) and we don't use RLS. All testing goes through pytest.

## Running Tests

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit

# Integration tests only
uv run pytest tests/integration

# Stop on first failure
uv run pytest -x

# Run tests matching a keyword
uv run pytest -k "test_trading"

# Verbose output
uv run pytest -v
```

## CI/CD

Backend tests run in GitHub Actions on every PR that changes files in `sevino-api/`.

### Workflow (`.github/workflows/backend.yml`)

1. Checkout repo.
2. Set up Python + uv.
3. `uv sync` to install dependencies.
4. Spin up Postgres service container (GitHub Actions built-in).
5. `alembic heads` — fail if multiple heads exist (catches migration conflicts).
6. `alembic upgrade head` against the test database.
7. `uv run pytest` — run all tests.
8. If tests pass and branch is `main`, Railway auto-deploys.

The workflow only triggers on changes to `sevino-api/**` — app-only PRs don't run backend tests.

## What to Test for MVP

### Test from day one

- **Auth flow** — JWT validation, token expiry, invalid/missing token handling.
- **Trade execution** — parsing user intent, constructing Alpaca orders, handling errors and edge cases (insufficient funds, market closed, invalid symbol).
- **Funding flow** — Plaid token exchange, ACH relationship creation, deposit/withdrawal requests.
- **API response shapes** — ensure endpoint responses match the contract the iOS app expects.
- **Background jobs** — verify jobs are enqueued with correct parameters, worker processes them correctly.

### Skip for now

- Load/performance testing (premature until real users).
- End-to-end tests against real Alpaca/Plaid sandboxes in CI (slow and flaky — mock instead).

## Manual Sandbox Testing

Separate from automated tests. This is the team manually testing real API flows on a simulator.

- **Alpaca sandbox:** Full brokerage simulation — create accounts, KYC, fund accounts, place trades. All fake money.
- **Plaid sandbox:** Use `user_good` / `pass_good` as test credentials to link fake bank accounts.
- **Local `.env`** points at sandbox API keys, so running the app locally exercises real API flows.
- Test edge cases manually: KYC rejection, ACH failure, order rejection, insufficient funds, market hours behavior.