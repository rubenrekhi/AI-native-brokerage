# Plaid + ACH Funding

Reference for the backend side of bank linking and ACH transfers. Covers the shipped flow, the components involved, security posture, and deferred items.

The iOS counterpart lives at `sevino-app/docs/funding.md`. Broader Alpaca Broker API usage (trading, accounts, market data, FDIC sweep) lives at `docs/alpaca-integration.md`.

---

## What this feature does

A user with an ACTIVE brokerage account can link a bank via Plaid Link, then move money between that bank and their brokerage account via ACH. The backend orchestrates Plaid's token exchange, requests a processor token for Alpaca, and creates an ACH relationship on Alpaca's side. Transfers (deposits and withdrawals) route through Alpaca's Broker API.

## End-to-end flow

```
iOS                         Backend                        Plaid              Alpaca
 │                             │                             │                  │
 │  POST /v1/funding/          │                             │                  │
 │  link-token          ──────▶│  create link_token  ───────▶│                  │
 │                      ◀──────│ ◀────────── link_token ─────│                  │
 │                             │                             │                  │
 │  Plaid Link sheet opens     │                             │                  │
 │  user auths with bank       │                             │                  │
 │  → public_token + metadata  │                             │                  │
 │                             │                             │                  │
 │  POST /v1/funding/          │                             │                  │
 │  link-bank           ──────▶│  exchange public ──────────▶│                  │
 │                             │ ◀────── access_token ───────│                  │
 │                             │  processor_token ──────────▶│                  │
 │                             │ ◀──── processor_token ──────│                  │
 │                             │  create ach_relationship ───┼─────────────────▶│
 │                             │ ◀────────── relationship ───┼──────────────────│
 │                             │  encrypt access_token,      │                  │
 │                             │  persist PlaidItem +        │                  │
 │                             │  AchRelationship locally    │                  │
 │                      ◀──────│ ◀── AchRelationshipResponse │                  │
```

Subsequent operations hit the backend, which reads local DB state and delegates to Alpaca:

- `GET  /v1/funding/ach-relationships` — lists active (non-canceled) relationships
- `DELETE /v1/funding/ach-relationships/{id}` — unlinks (Alpaca DELETE then local soft-delete)
- `POST /v1/funding/transfers` — creates a deposit (`INCOMING`) or withdrawal (`OUTGOING`)
- `GET  /v1/funding/transfers` — lists transfers from Alpaca with merged local bank metadata

## Components

| Layer | Module | Responsibility |
|---|---|---|
| Route | `app/routes/funding.py` | FastAPI router. Auth + schema validation + delegate to service. |
| Schemas | `app/schemas/funding.py` | Request/response Pydantic models. |
| Service | `app/services/funding.py` | `FundingService` — the only place combining Plaid + Alpaca + repos. |
| Service | `app/services/plaid.py` | `PlaidService` — async wrapper over `plaid-python` (link-token, exchange, processor token). |
| Service | `app/services/alpaca_broker.py` | `AlpacaBrokerService` funding methods (ACH CRUD + transfer CRUD). |
| Service | `app/services/encryption.py` | Fernet helper for encrypting Plaid access tokens at rest. |
| Repository | `app/repositories/plaid_item.py` | DAO for `plaid_items`. Owns encrypt/decrypt boundary. |
| Repository | `app/repositories/ach_relationship.py` | DAO for `ach_relationships`. Soft-delete only. |
| Model | `app/models/plaid_item.py` | ORM model. `passive_deletes=True` on children (see "Cascade" below). |
| Model | `app/models/ach_relationship.py` | ORM model. `plaid_item_id` FK is `ON DELETE SET NULL`. |

## API contract

All endpoints require JWT auth and inherit the global 120/minute per-user rate limit (`app/rate_limit.py`). Responses follow `{error, code, detail?}` on non-2xx.

### `POST /v1/funding/link-token`
```
request:  {}
response: { link_token: string }
```

### `POST /v1/funding/link-bank`
```
request:  {
  public_token: string,
  account_id: string,             # Plaid accounts[0].id
  institution_name: string?,      # display-only, trusted verbatim
  account_mask: string?,
  account_name: string?,
  nickname: string?
}
response: AchRelationshipResponse
errors:   409 ACCOUNT_NOT_ACTIVE, 409 BANK_ALREADY_LINKED, 422 ALPACA_ERROR, 422 VALIDATION_ERROR
```

### `GET /v1/funding/ach-relationships`
```
response: { relationships: [AchRelationshipResponse] }
```
Filters out `status = CANCELED`.

### `DELETE /v1/funding/ach-relationships/{id}`
```
response: 204 No Content
errors:   404 NOT_FOUND, 503 ALPACA_UNAVAILABLE
```
Alpaca DELETE first; on 2xx or 404, soft-delete locally. On 5xx, local row untouched.

### `POST /v1/funding/transfers`
```
request:  {
  relationship_id: uuid,          # local AchRelationship PK, NOT Alpaca's
  amount: Decimal (gt=0, max_digits=12, decimal_places=2),
  direction: "INCOMING" | "OUTGOING"
}
response: TransferResponse
errors:   409 RELATIONSHIP_CANCELED, 409 ACCOUNT_NOT_ACTIVE, 422 ALPACA_ERROR, 422 VALIDATION_ERROR
```
`amount` is quantized to 2 decimal places before forwarding to Alpaca.

### `GET /v1/funding/transfers`
```
query:    limit (default 50, max 100), offset
response: { transfers: [TransferResponse] }
```
Merges local `nickname` / `account_mask` / `institution_name` onto each Alpaca record under `bank`, including relationships that have been canceled (historical rows retain their metadata).

## Security posture

### Plaid access tokens encrypted at rest
`PlaidItemRepository.create` calls `encryption.encrypt` before writing to `plaid_items.plaid_access_token`. `get_access_token_plaintext` is the only way out. MultiFernet supports comma-separated keys in `PLAID_FERNET_KEY` for rotation — the first key is used for encryption, all keys are tried on decrypt. Rotation requires a process restart (cached with `@lru_cache`); matches Railway's blue/green deploy model.

Plaintext access tokens exist only in memory inside `PlaidService`, `FundingService.link_bank`, and `PlaidItemRepository`. They are never logged.

### Response shapes whitelist outbound fields
`TransferResponse` uses `extra="ignore"`, so Alpaca-internal fields (`account_id`, `relationship_id`, `type`, `reason`, etc.) are dropped at the boundary instead of being forwarded to iOS.

### Auth + rate limit
All endpoints require JWT auth via `get_current_user`. slowapi middleware enforces the 120/minute per-user default from `Limiter(default_limits=["120/minute"])`. No per-endpoint overrides.

## Error model

Errors map to the standard `error_response` helper (`app/exceptions.py`):

| Code | Status | Meaning |
|---|---|---|
| `ACCOUNT_NOT_ACTIVE` | 409 | Brokerage row missing or `account_status != "ACTIVE"`. `detail.account_status` carries the current value. |
| `BANK_ALREADY_LINKED` | 409 | Alpaca returned 409 from `create_ach_relationship`. iOS refreshes relationships and can show the existing link. |
| `RELATIONSHIP_CANCELED` | 409 | User tried to transfer through a canceled relationship. |
| `ALPACA_ERROR` | 422 | Alpaca 4xx for any non-409 reason. Message forwarded verbatim; `detail` carries Alpaca's `{code, message}`. |
| `ALPACA_UNAVAILABLE` | 503 | Alpaca 5xx or unreachable. |
| `VALIDATION_ERROR` | 422 | Request failed Pydantic validation. |
| Plaid errors | 422 | `PlaidServiceError.code` forwarded (e.g. `INVALID_PUBLIC_TOKEN`, `INVALID_CREDENTIALS`). |

## Idempotency + consistency

### Fast-path lookup
Before calling Plaid's processor-token endpoint, `link_bank` checks `PlaidItemRepository.get_by_plaid_item_id(plaid_item_id)`. If the item exists with an active relationship, the existing relationship is returned without any further external calls. Catches the common iOS network-retry case.

### IntegrityError race recovery
`plaid_items.plaid_item_id` has a `UNIQUE` constraint. If two concurrent requests race past the fast-path, the loser gets an `IntegrityError` on insert. The code catches it, rolls back, re-reads by `plaid_item_id`, and returns the winning request's relationship.

### Orphan-state compensation
After Alpaca creates a relationship, the local DB inserts can still fail (connection blip, pod OOM, unexpected constraint). If any step between the Alpaca call and the local `AchRelationship.create` fails, the code deletes the Alpaca relationship as a compensating action — otherwise retries would hit `BANK_ALREADY_LINKED` forever on an orphan we have no local record of. Compensation is best-effort: if the cleanup itself fails, the original exception still surfaces and the orphan is logged for operator reconciliation (`link_bank_alpaca_compensation_failed`).

### Cascade
`AchRelationship.plaid_item_id` uses `ON DELETE SET NULL` at the DB level. The ORM pairs this with `passive_deletes=True` on `PlaidItem.ach_relationships` so that deleting a PlaidItem does not cascade-delete child AchRelationship rows — the soft-delete rule is preserved even if a PlaidItem gets hard-deleted in the future (e.g. a cleanup job).

## Observability

Structured log events fire at boundary points. All include `user_id` for correlation.

| Event | Level | Source |
|---|---|---|
| `link_token_created` | info | `create_link_token` success |
| `funding_blocked_account_not_active` | warning | Any funding call blocked by inactive brokerage |
| `link_bank_idempotent_hit` | info | Fast-path return |
| `link_bank_race_resolved` | info | IntegrityError race recovered |
| `link_bank_duplicate_attempt` | warning | Alpaca 409 → `BANK_ALREADY_LINKED` |
| `link_bank_completed` | info | Happy path return |
| `link_bank_alpaca_compensation_succeeded` | info | Orphan cleanup succeeded |
| `link_bank_alpaca_compensation_failed` | error | Orphan cleanup failed — operator action required |
| `transfer_initiated` | info | After `alpaca.create_transfer` returns |
| `unlink_failed_alpaca_unavailable` | warning | Alpaca 5xx on DELETE before re-raise |
| `bank_unlinked` | info | After local soft-delete |
| `alpaca_ach_relationship_already_gone` | info | Alpaca 404 on DELETE (idempotent unlink) |

No tokens (access, public, processor) are ever logged.

## Running the smoke scripts

Prereqs: `make infra` + real Plaid sandbox + Alpaca sandbox creds in `.env`.

```bash
uv run python scripts/seed_funding_sandbox.py   # creates funding-smoke@sevino.test + fresh Alpaca sandbox account
make server                                     # in another terminal
source scripts/.funding_smoke_env               # env set by seeder

bash scripts/funding_smoke.sh                   # full happy path (link + deposit + history + unlink)
bash scripts/funding_withdraw_smoke.sh          # adds deposit settle wait + withdraw
bash scripts/funding_withdraw_smoke.sh --assume-settled   # withdraw only, using an existing relationship
bash scripts/funding_errors_smoke.sh            # error-branch coverage
```

## Database schema

Two branch-owned tables:

- **`plaid_items`** — one row per linked Plaid item. `plaid_access_token` stored as Fernet ciphertext. `plaid_item_id` has a `UNIQUE` constraint (migration `339563b12284`) to guarantee `link-bank` idempotency at the DB level. Status is free-form TEXT: `active`, `inactive`, `requires_reauth` (reserved for re-auth flow).
- **`ach_relationships`** — one row per user ↔ bank link. `plaid_item_id` FK is nullable with `ON DELETE SET NULL`. Status values: `QUEUED`, `APPROVED`, `CANCELED`, plus whatever Alpaca returns during its state transitions. Canceled rows are kept for transfer-history merge.

Status constants live next to their repositories (`repositories/plaid_item.py:STATUS_*`, `repositories/ach_relationship.py:STATUS_CANCELED`, `repositories/brokerage_account.py:STATUS_ACTIVE`).

## Deferred / known gaps

Tracked in Linear under the **Alpaca — Bank Linking & Transfers (+Plaid)** project:

- **SEV-222** — Plaid OAuth institutions (TD, Chase, BofA, etc.). Needs `redirect_uri` registration in Plaid Dashboard, Universal Links plumbing on iOS (AASA file, Associated Domains capability, `.onOpenURL` handler that resumes LinkKit). Blocker for any real-user launch that links a major U.S. bank.
- **SEV-223** / **SEV-227** — Deposit/Withdraw UI (Shivam) + backend wiring (Tharsihan). Backend `POST /v1/funding/transfers` is already live and unit-tested; iOS buttons currently have empty `action: {}` closures per Locked Decision #1.
- **SEV-224** / **SEV-228** — Transfer history UI (Shivam) + backend wiring. Backend `GET /v1/funding/transfers` is live; no iOS surface yet.
- **SEV-225** — `ITEM_LOGIN_REQUIRED` re-auth. Needs Plaid webhook consumer + update-mode link-token endpoint. `PLAID_ITEM_STATUS_REQUIRES_REAUTH` constant reserved. Status transitions not observed today (we don't consume webhooks yet, so `plaid_items.status` stays `active` forever after a successful link).
- **SEV-226** — Settings entry point for bank management (list + unlink + optional nickname edit). Backend DELETE endpoint is live; no iOS surface.
- **SEV-214** — Alpaca transfer status SSE listener. Today `ach_relationships.status` captures whatever Alpaca returned at creation time and never updates. Real-time status transitions on transfers (QUEUED → SENT_TO_CLEARING → COMPLETE) are invisible to our local DB; the `GET /v1/funding/transfers` endpoint papers over this by refetching from Alpaca each call.

Operational gaps worth tracking separately (no ticket yet):

- **No reconciliation job.** A periodic diff between our `ach_relationships` and Alpaca's `/v1/accounts/{id}/ach_relationships` would catch orphan drift from causes the in-process compensation can't reach (process crashes, mid-call pod kill).
- **No idempotency key on `POST /v1/funding/transfers`.** The endpoint accepts no client-supplied idempotency key. Mitigated today by the iOS button-disable pattern but a proper production feature should accept and forward `Idempotency-Key` to Alpaca.
- **No audit-log table.** `ach_relationships.status` is overwritten in place with no history. Dispute resolution would struggle.
- **No kill switch.** Funding endpoints can't be disabled without a redeploy.
