# AI smoke harness

Real-Anthropic end-to-end smoke tests for the chat-turn endpoint.

The harness spins up a local uvicorn server, hits
`POST /v1/conversations/{id}/turns` over HTTP, parses the SSE stream
into typed `Event` objects, and verifies persistence via the local
Supabase Postgres.

Each enabled test can cost real money. The harness pins to `MODELS.MAIN`
(currently `claude-sonnet-4-6`) because the runtime requests adaptive
thinking, which the older Haiku smoke-model plan does not support.

## When does this run?

### Locally

**Default `make test` skips this directory** (gated via
`collect_ignore_glob` in `conftest.py`). Run explicitly:

```bash
RUN_AI_SMOKE=1 uv run pytest tests/ai/smoke -v
```

Prerequisites — the conftest skips the suite with an actionable
message if any are missing:

* `make infra` running (Supabase Postgres on `:54322`, Redis on `:6379`)
* `ANTHROPIC_API_KEY` set to a real key in `.env` (placeholders
  starting with `ci-` or `test-` are rejected)
* All other env vars required by `app/config.py:Settings`

### CI (decision D10)

The `smoke-ai` job in `.github/workflows/ci.yml` runs when:

1. A PR touches any file under `sevino-api/app/ai/**` or
   `sevino-api/tests/ai/**` (detected via `dorny/paths-filter`), OR
2. A PR has the label `run-ai-smoke` (force-run for cross-cutting
   changes that don't touch `app/ai/` but might break the AI flow —
   e.g. changes to `app/exceptions.py`, `app/middleware/logging.py`,
   `app/database.py`), OR
3. A push lands on `main` (so a periodic signal still arrives even
   when no AI PRs land).

The job sets `RUN_AI_SMOKE=1` and pulls a real `ANTHROPIC_API_KEY`
from repo secrets. Fork PRs don't get repo secrets, so the variable
resolves to `""` and `_smoke_prereqs` skips the suite cleanly — no
spurious failures on contributor PRs.

## What's here

* `conftest.py` — server / DB / HTTP / SSE fixtures (B4.1). Pins the
  endpoint to `MODELS.MAIN` for the full session via a session-scoped
  `get_default_model_config` override.
* `test_hello.py` — smoke case: `"say hello"` turn (B4.2). Asserts the
  full SSE envelope and that `agent_turns` records a positive cost.
* `test_iteration_cap.py` — smoke case: iteration cap breach (B4.3).
  Overrides `get_hard_caps` to `HardCaps(max_iterations=0)` so the
  loop short-circuits with `terminal_state='iteration_limit'` before
  any Anthropic call (so this case bills nothing).

## Available fixtures

* `smoke_server` (session) — uvicorn on a free port, yields the base
  URL.
* `smoke_user` (function) — seeds a fresh user, installs a
  `get_current_user` override, deletes the user's full turn graph at
  teardown.
* `smoke_conversation_id` (function) — fresh UUID per test (the
  server creates the row implicitly on the first turn, per D6).
* `smoke_client` (function) — `httpx.AsyncClient` bound to the smoke
  server with API-key auth prefilled.
* `db_engine` (session, re-exported from `tests/integration/conftest.py`)
  — for verification queries against the persisted turn graph.

`parse_sse_event(sse)` is a helper that converts an
`httpx_sse.ServerSentEvent` into the typed `Event` from
`app/ai/transport/events.py`.

## Why default-skipped

Real Anthropic calls bill in CI minutes and dollars. The harness is off by
default and gated on explicit opt-in (`RUN_AI_SMOKE=1` locally; the CI secret
on workflows).
