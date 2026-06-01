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
- `DELETE /v1/funding/transfers/{id}` — cancels an in-flight transfer (Alpaca DELETE; no local write)

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
Filters out `status = CANCELED`. Before returning, refreshes each row's `status` from Alpaca via one `list_ach_relationships` call — Alpaca has no SSE stream for relationship lifecycle, so this is how we observe `QUEUED → APPROVED` and Alpaca-initiated `CANCEL_REQUESTED` transitions. Skipped when the brokerage account isn't ACTIVE. If the Alpaca call fails (4xx/5xx/unreachable), we log `ach_relationship_refresh_failed` and return the local rows as-is — this endpoint is informational, not a money precondition, so stale status is safe (`POST /transfers` does its own fresh refresh before acting).

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
errors:   409 RELATIONSHIP_CANCELED, 409 RELATIONSHIP_NOT_APPROVED,
          409 ACCOUNT_NOT_ACTIVE, 422 ALPACA_ERROR, 422 VALIDATION_ERROR
```
`amount` is quantized to 2 decimal places before forwarding to Alpaca. Before calling Alpaca, refreshes the relationship's `status` from Alpaca; transfers only proceed when `status = APPROVED`. Local `CANCELED` short-circuits before the refresh. Alpaca-side `CANCEL_REQUESTED` surfaces as `RELATIONSHIP_CANCELED` (same user-facing semantics as our soft-delete). Any other non-`APPROVED` value (`QUEUED`, `PENDING`) surfaces as `RELATIONSHIP_NOT_APPROVED` with `detail.status` carrying the current value so iOS can distinguish "still verifying" from "unusable."

### `GET /v1/funding/transfers`
```
query:    limit (default 50, max 100), offset
response: { transfers: [TransferResponse] }
```
Merges local `nickname` / `account_mask` / `institution_name` onto each Alpaca record under `bank`, including relationships that have been canceled (historical rows retain their metadata).

### `DELETE /v1/funding/transfers/{transfer_id}`
```
response: 204 No Content
errors:   404 NOT_FOUND, 409 TRANSFER_NOT_CANCELABLE, 409 ACCOUNT_NOT_ACTIVE,
          422 ALPACA_ERROR, 503 ALPACA_UNAVAILABLE
```
Cancels an in-flight ACH transfer. `transfer_id` is Alpaca's transfer id (a string), **not** a local PK — transfers are never persisted locally. Ownership is enforced by scoping to the caller's own `alpaca_account_id` (resolved via the active-brokerage gate): a `transfer_id` that isn't theirs isn't in their list and surfaces as `404`. Only transfers in `QUEUED` / `APPROVAL_PENDING` / `PENDING` (`CANCELABLE_TRANSFER_STATUSES`) can be canceled — anything else (a `COMPLETE`/`REJECTED`/`RETURNED` transfer, an already-`CANCELED` one on a double-cancel, or `SENT_TO_CLEARING` and beyond) is rejected with `TRANSFER_NOT_CANCELABLE` (`detail.status` carries the current value) before calling Alpaca. If a transfer races past the window between the pre-flight read and the DELETE, Alpaca returns `422 {"code":40010001,"message":"transfer is not cancelable"}`, which is mapped to the same `409 TRANSFER_NOT_CANCELABLE`. No local write — the next `GET /transfers` reflects the canceled status.

The cancelable-status boundary (and the `40010001` error code) were verified against the Alpaca sandbox; the public docs are silent on both.

## Security posture

### Plaid access tokens encrypted at rest
`PlaidItemRepository.create` calls `encryption.encrypt` before writing to `plaid_items.plaid_access_token`. `get_access_token_plaintext` is the only way out. MultiFernet supports comma-separated keys in `PLAID_FERNET_KEY` for rotation — the first key is used for encryption, all keys are tried on decrypt. Rotation requires a process restart (cached with `@lru_cache`); matches Railway's blue/green deploy model.

Plaintext access tokens exist only in memory inside `PlaidService`, `FundingService.link_bank`, and `PlaidItemRepository`. They are never logged.

### Response shapes whitelist outbound fields
`TransferResponse` uses `extra="ignore"`, so Alpaca-internal fields (`account_id`, `relationship_id`, `type`, etc.) are dropped at the boundary instead of being forwarded to iOS. `reason` is deliberately exposed — it carries Alpaca's explanation for `RETURNED` / `REJECTED` transfers (e.g. NACHA return codes like `R01 Insufficient funds`), which iOS needs to render a useful failure message.

### Auth + rate limit
All endpoints require JWT auth via `get_current_user`. slowapi middleware enforces the 120/minute per-user default from `Limiter(default_limits=["120/minute"])`. No per-endpoint overrides.

## Error model

Errors map to the standard `error_response` helper (`app/exceptions.py`):

| Code | Status | Meaning |
|---|---|---|
| `ACCOUNT_NOT_ACTIVE` | 409 | Brokerage row missing or `account_status != "ACTIVE"`. `detail.account_status` carries the current value. |
| `BANK_ALREADY_LINKED` | 409 | Alpaca returned 409 from `create_ach_relationship`. iOS refreshes relationships and can show the existing link. |
| `RELATIONSHIP_CANCELED` | 409 | User tried to transfer through a canceled relationship — either locally soft-deleted via unlink, or Alpaca-side `CANCEL_REQUESTED` observed during the pre-transfer refresh. |
| `RELATIONSHIP_NOT_APPROVED` | 409 | Relationship is still in `QUEUED` or `PENDING` at Alpaca after refresh. `detail.status` carries the current value. iOS can surface "still being verified — try again in a few minutes." |
| `TRANSFER_NOT_CANCELABLE` | 409 | Cancel attempted on a transfer outside `QUEUED`/`APPROVAL_PENDING`/`PENDING` — caught by the pre-flight status gate (incl. double-cancel of an already-`CANCELED` transfer), or by Alpaca's `422 code 40010001` when it raced past the window. `detail.status` carries the pre-flight status when known. |
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
| `ach_relationship_status_refreshed` | info | Refresh-on-read flipped a local status to match Alpaca (e.g. QUEUED → APPROVED). Carries `status_from`/`status_to`. |
| `transfer_blocked_relationship_not_approved` | warning | Pre-transfer refresh showed non-APPROVED status (QUEUED/PENDING). |
| `transfer_blocked_relationship_cancel_requested` | warning | Pre-transfer refresh showed Alpaca-side CANCEL_REQUESTED. |
| `link_bank_alpaca_compensation_succeeded` | info | Orphan cleanup succeeded |
| `link_bank_alpaca_compensation_failed` | error | Orphan cleanup failed — operator action required |
| `transfer_initiated` | info | After `alpaca.create_transfer` returns |
| `transfer_canceled` | info | After `alpaca.cancel_transfer` succeeds |
| `transfer_cancel_blocked_not_cancelable` | info | Pre-flight gate rejected a cancel (status not in `CANCELABLE_TRANSFER_STATUSES`) |
| `unlink_failed_alpaca_unavailable` | warning | Alpaca 5xx on DELETE before re-raise |
| `bank_unlinked` | info | After local soft-delete |
| `alpaca_ach_relationship_already_gone` | info | Alpaca 404 on DELETE (idempotent unlink) |

No tokens (access, public, processor) are ever logged.

## Background jobs

### `reconcile_funding` (hourly at :15 UTC)

ARQ cron registered in `app/worker.py`; implementation in `app/tasks/reconcile_funding.py`. Diffs every non-canceled local `ach_relationship` (whose brokerage account is `ACTIVE`) against Alpaca's `/v1/accounts/{id}/ach_relationships`. Closes the two blind spots the refresh-on-read pattern can't cover:

- **Server-side cancellation** — Alpaca cancels a relationship (compliance, fraud, account closure) and the user never opens the app to trigger a refresh.
- **Silent transitions** — `QUEUED → APPROVED` while the user is away; without the cron we'd only notice the next time they hit `GET /v1/funding/ach-relationships`.

Per-account error isolation: one account's Alpaca failure (network blip, 4xx) is logged via `funding_reconcile_account_failed` and the sweep continues. PR-preview environments short-circuit at the top.

Transfer reconciliation is intentionally out of scope here — once SEV-214's transfer SSE listener lands, it owns transfer state. This cron is the belt to that future SSE's suspenders for relationships only.

### Drift events

Every detected drift emits a single structured log `funding_reconcile_drift`:

| Field | Type | Meaning |
|---|---|---|
| `kind` | `status_change` \| `server_side_cancellation` | Status changed at Alpaca, or row disappeared entirely. |
| `relationship_pk` | uuid | Local `ach_relationships.id`. |
| `user_id` | uuid | Owner of the relationship. |
| `alpaca_relationship_id` | string | Alpaca's id, useful for support correlation. |
| `status_from` | string | Local status before the update. |
| `status_to` | string | New status (`CANCELED` for server-side cancellation). |

A run-summary `funding_reconcile_complete` log fires once per successful run with counts: `checked`, `drifted`, `canceled_server_side`, `errored_accounts`.

### Operator playbook

- **`kind=server_side_cancellation`** — Alpaca dropped the link, usually compliance or account closure on their side. Treat the same as a user-initiated unlink for support purposes. If volume spikes, ping Alpaca to ask why.
- **`kind=status_change` to anything other than `APPROVED` or `CANCEL_REQUESTED`** — unexpected. Pull the row by `relationship_pk` and inspect Alpaca's response shape for new lifecycle values.
- **Alert: no `funding_reconcile_complete` log in ~3h** — configured in Sentry/Logflare, not in code. Indicates the worker is down or the cron stopped registering. Check `make worker` health + arq logs.

To verify the cron against real Alpaca sandbox: `scripts/funding_reconcile_smoke.sh` (see "Running the smoke scripts" below).

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
bash scripts/funding_smoke.sh --skip-unlink && \
  bash scripts/funding_reconcile_smoke.sh       # reconcile cron drift + server-side cancel (SEV-580)
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
- **SEV-214** — Alpaca transfer status SSE listener. Transfer lifecycle transitions (QUEUED → SENT_TO_CLEARING → COMPLETE) are only observed when the user opens the history screen; `GET /v1/funding/transfers` refetches from Alpaca each call. Worth deferring until push notifications or a local transfers table actually need push updates — today the refresh-on-read pattern is correct and simpler.
- **ACH relationship status.** Alpaca does **not** publish an SSE stream for the `ach_relationship` resource — only for `transfer`. `ach_relationships.status` is kept fresh via refresh-on-read inside `GET /v1/funding/ach-relationships` and `POST /v1/funding/transfers`, plus the hourly `reconcile_funding` cron (see "Background jobs") for users who never open the app.

Operational gaps worth tracking separately (no ticket yet):

- **No idempotency key on `POST /v1/funding/transfers`.** The endpoint accepts no client-supplied idempotency key. Mitigated today by the iOS button-disable pattern but a proper production feature should accept and forward `Idempotency-Key` to Alpaca.
- **No audit-log table.** `ach_relationships.status` is overwritten in place with no history. Dispute resolution would struggle.
- **No kill switch.** Funding endpoints can't be disabled without a redeploy.
