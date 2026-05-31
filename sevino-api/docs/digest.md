# Daily Digest

Daily Digest is a persisted, per-user morning card stack. The API stores one
`digest_snapshots` row per `(user_id, ny_local_date)` and serves it from
`GET /v1/digest/today`.

Linear project context: [SEV-645](https://linear.app/sevino/issue/SEV-645/t15-end-to-end-verification-fixtures-observability).

## Architecture

```
Alpaca portfolio + DB profile + favorited radar + market clock
  -> DigestContext
  -> 9 generators run concurrently
  -> cross-generator enrichment
  -> heuristic shortlist, capped at 15
  -> Anthropic reranker, 3-7 cards
  -> digest_snapshots JSONB card stack
```

Core modules:

- `app/services/digest/context.py` builds `DigestContext`.
- `app/services/digest/generators/` contains the independent card sources.
- `app/services/digest/service.py` coordinates generation, enrichment,
  reranking, persistence, logging, and Sentry capture.
- `app/services/digest/reranker.py` calls Anthropic and falls back to the
  heuristic order when the model path is unavailable or invalid.
- `app/tasks/generate_daily_digest.py` is the ARQ cron entrypoint.
- `app/routes/digest.py` serves today/dismiss and performs lazy generation.

## Pipeline

`DigestService.generate_for_user(user_id)` builds context once, runs the known
generators with `asyncio.gather`, enriches candidates across generators, sorts
the top 15 by weighted impact, asks Anthropic for final ordering, assigns
priority, and upserts the snapshot for the user's New York local date.

`DigestService.preview_for_user(user_id)` runs the same pipeline without the
repository upsert. `make digest-dry-run USER_EMAIL=...` uses this path and
prints ordered card JSON to stdout.

## Cron And Lazy Fallback

The worker schedules `generate_daily_digest` at 13:00 and 14:00 UTC. Running
twice covers 9am New York local time across daylight-saving changes; repository
upsert idempotency keeps duplicate runs from creating duplicate snapshots.

The cron selects users with recent activity who do not already have a snapshot
for the New York local date. Each user generation receives shared Alpaca, FMP,
market-data, and Anthropic clients from the worker context.

If `GET /v1/digest/today` is called after 9am New York time and no snapshot
exists, the route attempts lazy generation with a 30 second timeout. Lazy hits
emit `digest.lazy_fallback.hit` with `counter="digest_lazy_fallback_total"` and
`increment=1`.
Timeouts roll back the session and return `204`.

## Generators

- `DividendsGenerator`: recent positive dividend payments.
- `PendingOrdersGenerator`: filled, partially filled, or skipped recurring
  order activity since the prior market close.
- `RadarRefreshGenerator`: new AI radar rows created today.
- `BigMovesGenerator`: meaningful overnight or pre-market moves in holdings.
- `WatchlistMovesGenerator`: meaningful moves in favorited radar symbols.
- `MarketContextGenerator`: S&P 500 and Nasdaq context card.
- `EarningsResultsGenerator`: latest reported earnings for held positions.
- `UpcomingEarningsGenerator`: held positions reporting in the next week.
- `NewsGenerator`: recent holdings-related stock news.

## Observability

Each generator emits `digest.generator.completed` with:

- `name`
- `latency_ms`
- `candidate_count`
- `error`
- `user_id`

Generator failures are isolated to that generator, captured in Sentry, and
tagged with `digest.generator=<name>`.

Overall generation emits `digest.generation.completed` with:

- `user_id`
- `total_latency_ms`
- `final_card_count`
- `reranker_fallback`
- `reranker_fallback_reason`
- `card_kinds`
- `ny_local_date`
- `persisted`

Reranker fallback adds a warning-level Sentry breadcrumb with the fallback
reason before returning the heuristic order.

## Local Verification

Seed deterministic fixture data and verify the expected card set:

```sh
uv run python scripts/seed_digest.py
```

Run a live dry run for an existing local user without persisting:

```sh
make digest-dry-run USER_EMAIL=user@example.com
```

Watch `make server` output while hitting `GET /v1/digest/today` or running the
scripts to verify the structured log events above.
