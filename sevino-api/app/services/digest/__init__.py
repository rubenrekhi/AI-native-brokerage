"""Daily Digest: an LLM-curated, per-user card stack generated once each
morning and persisted as a row in `digest_snapshots`.

Submodules:
- `cards` — the `DigestCard` discriminated union (SSE/JSONB wire format)
- `types` — `DigestContext`, `CardCandidate`, the `Generator` protocol
- `context` — `build_context`, the per-user input gather
- `generators` — registered card generators for portfolio activity
- `moves` — overnight/pre-market move detection helpers
- `service` — `DigestService` (generate / read / dismiss)
"""
