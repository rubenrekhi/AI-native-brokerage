# sevino-api/Makefile

# Start all infrastructure (run once when you sit down to work)
infra:
	supabase start
	brew services start redis

# Start the API server (terminal 1)
server:
	uv run uvicorn app.main:app --reload --no-access-log

# Start the background worker (terminal 2)
worker:
	uv run arq app.worker.WorkerSettings

# Run full digest generation for a user without writing a snapshot
digest-dry-run:
	@test -n "$(USER_EMAIL)" || (echo "USER_EMAIL is required, e.g. make digest-dry-run USER_EMAIL=user@example.com" >&2; exit 2)
	@uv run python scripts/digest_dry_run.py --user-email "$(USER_EMAIL)"

# Run all tests
test:
	uv run pytest

# Run unit tests only
test-unit:
	uv run pytest tests/unit tests/ai/unit

# Create a new migration
migration:
	uv run alembic revision --autogenerate -m "$(msg)"

# Apply migrations
migrate:
	uv run alembic upgrade head

# Stop all infrastructure
down:
	supabase stop
	brew services stop redis
