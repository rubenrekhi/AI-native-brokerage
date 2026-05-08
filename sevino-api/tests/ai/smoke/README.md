# AI smoke harness

Real-Anthropic end-to-end smoke tests for the chat-turn endpoint.

The harness spins up a local uvicorn server, hits
`POST /v1/conversations/{id}/turns` over HTTP, parses the SSE stream
into typed `Event` objects, and verifies persistence via the local
Supabase Postgres.

Each test costs real money — the agent calls Claude (Haiku tier per
decision D9 in `sevino-api/docs/ai-v0-plan.md`).

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

Once B4.4 lands the workflow update (`.github/workflows/ci.yml`), the
smoke harness will run when:

1. A PR touches any file under `sevino-api/app/ai/**` or
   `sevino-api/tests/ai/**`, OR
2. A PR has the label `run-ai-smoke` (force-run for cross-cutting
   changes that don't touch `app/ai/` but might break the AI flow —
   e.g. changes to `app/exceptions.py`, `app/middleware/logging.py`,
   `app/database.py`), OR
3. A push lands on `main` (so a daily signal still arrives even when
   no AI PRs land).

All paths are gated on the `RUN_AI_SMOKE` GitHub Actions secret being
present — contributor forks without the secret are no-ops, not
failures.

## What's here

* `conftest.py` — server / DB / HTTP / SSE fixtures (B4.1). Pins the
  endpoint to `MODELS.SMOKE` (Haiku) for the full session via a
  session-scoped `get_default_model_config` override.
* `test_hello.py` — smoke case: `"say hello"` turn (B4.2). Asserts the
  full SSE envelope and that `agent_turns` records a positive cost.
* `test_iteration_cap.py` — smoke case: iteration cap breach (B4.3).
  Overrides `get_hard_caps` to `HardCaps(max_iterations=0)` so the
  loop short-circuits with `terminal_state='iteration_limit'` before
  any Anthropic call (so this case bills nothing).
* (Phase 3) `test_get_stock_info.py` — AMD price query exercising
  `get_stock_info` (C5.3).

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

Real Anthropic calls bill in CI minutes and dollars. Per risk R10 in
`docs/ai-v0-plan.md`, the harness is off by default and gated on
explicit opt-in (`RUN_AI_SMOKE=1` locally; the CI secret on workflows).
