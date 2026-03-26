# saturn-api/Makefile

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

# Run all tests
test:
	uv run pytest

# Run unit tests only
test-unit:
	uv run pytest tests/unit

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