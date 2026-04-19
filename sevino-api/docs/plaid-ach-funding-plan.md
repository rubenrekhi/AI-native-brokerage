# Plaid + ACH Funding — Implementation Plan

## Context

Bank account linking via Plaid + ACH deposits/withdrawals via Alpaca. Maps to PRD `FR-3.3`, `FR-3.4`, `FR-3.5`, and the 70%-funding-in-7-days activation target. This is the next logical step after onboarding — once a user's brokerage account is `ACTIVE`, they need to fund it before they can trade.

Full technical reference lives in `docs/plaid-integration.md` and the Funding section of `docs/alpaca-integration.md`. This document is the branch plan: what ships, what doesn't, what exists, what's missing.

Branch: `tharsihanariyanayagam/plaid-ach-funding`

---

## In Scope — This Branch

### Backend

- `PlaidService` with `create_link_token`, `exchange_public_token`, `create_processor_token`
- `AlpacaBrokerService` extended with ACH relationships (create, list, delete) and transfers (create, list)
- `FundingService` orchestrating Plaid steps 3→4→5 as one atomic "link bank" operation, plus transfer creation and soft-delete unlink
- `PlaidItemRepository` + `AchRelationshipRepository`
- Fernet (actually `MultiFernet` for rotation-readiness) encryption helper for `plaid_items.plaid_access_token` at rest
- Pydantic schemas in `app/schemas/funding.py`
- Routes mounted at `/v1/funding/*`
- Soft-delete discipline: `ach_relationships.status = 'CANCELED'` and `plaid_items.status = 'inactive'` — never hard-delete
- Config additions: `plaid_fernet_key`, `plaid_base_url` computed property (sandbox vs. prod)
- Unit + integration tests (Plaid + Alpaca clients mocked)

### Frontend

- Settings screen scaffold + navigation from `HomeView`'s menu button (currently a dead placeholder)
- "Link a bank account" button → backend-minted `link_token` → present Plaid `LinkViewController`
- `onSuccess` callback → send `public_token` + `account_id` to `POST /v1/funding/link-bank`
- Linked-banks list view (Settings → Accounts → Funding)
- Deposit + withdrawal amount-entry views with confirmation step
- Transfer history view (merges Alpaca records with our bank nicknames)
- Unlink bank confirmation + error handling
- Codable DTOs matching the new backend schemas

---

## Out of Scope — Explicitly Deferred

- **SSE listener for `/v2/events/funding/status`** — waiting for the KYC-sync dev's SSE infra to land, then we bolt on a funding consumer. Until then, transfer statuses are whatever Alpaca returned on `POST /transfers` (typically `QUEUED`). iOS refreshes via `GET /v1/funding/transfers` on screen open / pull-to-refresh.
- **`ITEM_LOGIN_REQUIRED` re-auth via update mode** — small follow-up branch right after this one. Per Robinhood-minimal MVP scope (see `docs/plaid-integration.md` → "Plaid Link Re-authentication").
- **Plaid webhooks** (`PENDING_DISCONNECT`, `PENDING_EXPIRATION`, etc.) — past beta.
- **Manual routing/account entry + micro-deposit fallback** (Alpaca's non-Plaid path) — past beta.
- **Second aggregator** (Flinks / Wealthica) — not until Canadian expansion, which the PRD defers.
- **App-level transfer limits** — broker-level caps only for beta.

---

## What Already Exists (Relevant)

### Backend — reusable today

| Area | What's there | File |
|---|---|---|
| Dependencies | `plaid-python`, `cryptography` (Fernet) already installed | `pyproject.toml` |
| Config | `plaid_client_id`, `plaid_secret`, `plaid_env` already in `Settings` | `app/config.py:50-52` |
| Models | `PlaidItem` with all needed columns (item_id, access_token, account_id, institution metadata, status) | `app/models/plaid_item.py` |
| Models | `AchRelationship` with all needed columns + FK to `brokerage_accounts` and nullable FK to `plaid_items` | `app/models/ach_relationship.py` |
| Alpaca client | `AlpacaBrokerService` with OAuth2 + `_request` helper, `create/get/update_account` methods | `app/services/alpaca_broker.py` |
| Errors | `AlpacaBrokerError`, `AlpacaBrokerUnavailableError`, `NotFoundError`, `ConflictError` + global handlers | `app/exceptions.py` |
| Auth | `get_current_user` JWT dependency fully wired | `app/auth.py` |
| Middleware | Rate limiting, API key gate, correlation ID, request logging | `app/middleware/` |
| Test infra | `conftest.py` with `mock_db`, `authenticated_client`, real-DB integration fixtures | `tests/conftest.py` |

**No migration required.** The `plaid_items` and `ach_relationships` tables already exist with all needed columns.

### Frontend — reusable today

| Area | Status | File |
|---|---|---|
| Plaid LinkKit SDK | Wired as SPM dep (v6.4.7), zero integration code | `Package.resolved` |
| `APIClient` | Production-ready, generic get/post/put/patch/delete, JWT + snake/camel case built-in | `APIClient.swift` |
| `AuthService` | JWT plumbing complete, auto-attach on requests | `AuthService.swift` |
| `APIError` | Matches backend structured shape, convenience checks (`isAuthError`, `isRateLimited`, etc.) | `APIError.swift` |
| `AnyCodable` | For dynamic `detail` fields | `Utils/AnyCodable.swift` |
| Onboarding | Full 18-screen flow + KYC submission wired; post-onboarding routes to `HomeView` | `OnboardingContainerView.swift` |

---

## What's Missing & Needs to Be Built

### Backend

**New files**
- `app/services/plaid.py` — `PlaidService`
- `app/services/funding.py` — `FundingService` (orchestration + soft-delete)
- `app/services/encryption.py` — Fernet/MultiFernet helper: `encrypt(plaintext) -> str`, `decrypt(ciphertext) -> str`
- `app/repositories/plaid_item.py` — `PlaidItemRepository`
- `app/repositories/ach_relationship.py` — `AchRelationshipRepository`
- `app/schemas/funding.py` — Pydantic request/response models
- `app/routes/funding.py` — FastAPI router
- `tests/unit/test_plaid_service.py`
- `tests/unit/test_encryption.py`
- `tests/unit/test_funding_service.py`
- `tests/integration/test_funding.py`
- `tests/fixtures/mock_responses/plaid_link_token.json`
- `tests/fixtures/mock_responses/plaid_exchange.json`
- `tests/fixtures/mock_responses/plaid_processor_token.json`
- `tests/fixtures/mock_responses/alpaca_ach_relationship.json`
- `tests/fixtures/mock_responses/alpaca_transfer.json`

**Files to modify**
- `app/config.py` — add `plaid_fernet_key` (or `plaid_fernet_keys` as comma-separated for MultiFernet), add `plaid_base_url` computed property (`https://sandbox.plaid.com` vs. `https://production.plaid.com` based on `plaid_env`)
- `app/services/alpaca_broker.py` — add 5 methods:
  - `create_ach_relationship(account_id, processor_token)` → POST `/v1/accounts/{id}/ach_relationships`
  - `list_ach_relationships(account_id)` → GET
  - `delete_ach_relationship(account_id, relationship_id)` → DELETE
  - `create_transfer(account_id, relationship_id, amount, direction)` → POST `/v1/accounts/{id}/transfers` with `transfer_type: "ach"` + `timing: "immediate"`
  - `list_transfers(account_id, direction=None)` → GET
- `app/main.py` — mount the funding router with prefix `/v1/funding` + tag
- `.env.example` — add `PLAID_FERNET_KEY=` placeholder
- `app/models/plaid_item.py` — (optional) switch `plaid_access_token` to a custom `EncryptedType` column, OR leave as `Text` and encrypt/decrypt in the repository layer (leaning toward the second — simpler, no SQLAlchemy type juggling)

**API endpoints** (all `Depends(get_current_user)` + `Depends(get_db)`, default per-user rate limit)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/funding/link-token` | Mint a Plaid `link_token` for iOS |
| POST | `/v1/funding/link-bank` | Body: `public_token`, `account_id`, optional institution metadata. Runs steps 3→4→5 atomically. Idempotent on `plaid_item_id`. |
| GET | `/v1/funding/ach-relationships` | List the user's active linked banks |
| DELETE | `/v1/funding/ach-relationships/{id}` | Unlink (DELETE at Alpaca → soft-delete on our side) |
| POST | `/v1/funding/transfers` | Body: `relationship_id`, `amount`, `direction` (`INCOMING`/`OUTGOING`). Always sends `transfer_type: "ach"` + `timing: "immediate"` |
| GET | `/v1/funding/transfers` | Transfer history, merged with local bank nicknames |

### Frontend

**New files / views**
- `Views/Settings/SettingsView.swift` — scaffold with sections for Accounts, Personal Info, etc. (per PRD §5)
- Navigation wiring: `HomeView` menu button → `SettingsView`
- `Views/Funding/LinkedBanksView.swift` — list of linked banks, "Link a bank account" CTA, unlink confirmation
- `Views/Funding/LinkBankFlow.swift` — orchestrator that calls `POST /link-token`, presents `LinkViewController`, handles `onSuccess` → `POST /link-bank`, handles `onExit` / errors
- `Views/Funding/DepositView.swift` — amount entry + confirmation
- `Views/Funding/WithdrawView.swift` — amount entry + confirmation
- `Views/Funding/TransferHistoryView.swift`
- `ViewModels/Funding/FundingViewModel.swift` — replaces the placeholder; owns API calls + state
- `Models/Funding/*.swift` — Codable DTOs: `AchRelationshipDTO`, `LinkTokenDTO`, `LinkBankRequest`, `TransferDTO`, etc.
- `Services/FundingService.swift` (app side) — thin wrapper over `APIClient` for `/v1/funding/*`

**Plaid LinkKit integration** — the SDK is imported but used nowhere yet. Need:
- `LinkTokenConfiguration(token: linkToken, onSuccess: ..., onExit: ...)` per Plaid LinkKit Swift API
- Present via `UIViewControllerRepresentable` inside a SwiftUI sheet, or the newer SwiftUI `.sheet` pattern LinkKit exposes
- Pass `metadata.accounts[0].id` through on success — "Account Select: one account" in Plaid Dashboard guarantees one element

**Delete existing placeholder files** when their real counterparts land: `Views/Funding/FundingPlaceholder.swift`, `ViewModels/Funding/FundingViewModelPlaceholder.swift`, `Models/Funding/FundingModelPlaceholder.swift`

---

## Architecture Layers

```
Routes (app/routes/funding.py)
    ↓ calls FundingService only (no direct repo/client access in routes)
FundingService (app/services/funding.py)
    ↓ orchestrates PlaidService + AlpacaBrokerService + repositories
    ↓ handles soft-delete, idempotency, encryption round-trip
PlaidService, AlpacaBrokerService          Repositories
    ↓ external API calls                    ↓ DB queries
Plaid API, Alpaca Broker API               Postgres
```

Per-table repositories own their SQLAlchemy queries. Services never call `db.execute()` directly. Routes never call repositories directly.

---

## Soft-delete Rule (Must Remember)

- Unlinking a bank: `AlpacaBrokerService.delete_ach_relationship(...)` → then `ach_relationships.status = 'CANCELED'`. Row stays in DB to preserve `nickname` / `account_mask` for historical transfer display. See `docs/plaid-integration.md` → "Transfer History & Unlinking."
- Plaid item being permanently unusable: `plaid_items.status = 'inactive'`. Don't delete — `access_token` may be needed for audit / historical recovery.
- `GET /v1/funding/ach-relationships` must filter out `status = 'CANCELED'` by default.
- `GET /v1/funding/transfers` must **not** filter by relationship status — historical transfers can point to canceled relationships and should still display with their original bank nickname.

---

## Risks & Integration Points

### 1. Blocked by KYC sync for production
Alpaca returns `403` on ACH relationship creation if the brokerage account isn't `ACTIVE`. In prod, accounts stay `SUBMITTED` until the KYC sync branch (other dev) flips them. In sandbox, accounts typically go `ACTIVE` within seconds.

**Mitigation:** before calling Alpaca, `FundingService.link_bank` loads the user's `brokerage_accounts` row and returns a friendly error (e.g., `code: "ACCOUNT_NOT_ACTIVE"`, 409 or 422) if `account_status != 'ACTIVE'`. iOS surfaces "Your account is still being reviewed." rather than a 403 from Alpaca leaking through.

### 2. Transfer statuses won't live-update until SSE lands
Transfers return with `status: "QUEUED"` from `POST`. No push updates until the other dev's SSE infra ships and we add a funding consumer on top.

**Mitigation:** iOS pulls-to-refresh the transfer list. `GET /v1/funding/transfers` always calls Alpaca for fresh status — don't cache transfer statuses in our DB.

### 3. Re-auth branch depends on fields in this branch
The follow-up `ITEM_LOGIN_REQUIRED` branch will need:
- `plaid_items.status` to accept `'requires_reauth'` (TEXT column, so no migration — just a code constant)
- `PlaidService.create_update_mode_link_token(access_token)` — not in this branch
- A new route `POST /v1/funding/reauth-link-token`

**Action:** keep `plaid_items.status` as free-form TEXT for now. Document the known future values (`active`, `inactive`, `requires_reauth`) as a constant in `app/services/funding.py`.

### 4. Encryption key rotation
`MultiFernet` supports decrypting with any key in its list and encrypting with the first. If we ever rotate, prepend a new key to the env-var list. No automated rotation mechanism in this branch — document the manual process.

**Action:** `plaid_fernet_key` env var accepts a comma-separated list. First key is primary (used for encryption); subsequent keys are decrypt-only fallbacks used during rotation.

### 5. Idempotency on `link-bank`
If iOS retries after a network blip, we must not create a second `PlaidItem` row or a second Alpaca ACH relationship.

**Mitigation:**
- Unique constraint on `plaid_items.plaid_item_id` — DB-level guarantee
- Service checks for existing `PlaidItem` with same `plaid_item_id` before calling Plaid steps 4–5; if present, returns the existing relationship
- Alpaca returns `409 Conflict` on duplicate ACH relationship — service catches and returns existing row

### 6. Duplicate-bank-at-Alpaca scenario
User links the same physical bank twice (maybe different Plaid items but same routing/account at Alpaca's end). Alpaca returns `409`. We surface a friendly error (`code: "BANK_ALREADY_LINKED"`) and point to the existing relationship.

### 7. Frontend settings surface doesn't exist
The Settings screen itself is missing. Before funding UI can ship to users, someone has to build the Settings scaffold and navigate from `HomeView`. Calling this out because it's iOS-side non-trivial work (not a backend blocker).

### 8. Plaid sandbox vs. prod environment switching
Plaid has three envs: `sandbox`, `development` (deprecated for new accounts), `production`. `plaid_env` in our config drives which base URL we use. Document clearly that `development` is not supported.

### 9. Amount validation
- Pydantic: amount must be a positive `Decimal` with ≤ 2 decimal places
- Alpaca enforces minimums server-side; we return Alpaca's error message if they reject

### 10. Rate limits on Plaid
Plaid's free tier caps `/link/token/create` calls. Shouldn't matter for beta but worth knowing if we get noisy iOS retries. The default 120/min per-user limiter on our endpoint provides a natural ceiling.

---

## Dependencies Between Branches

| Branch | Status | Relationship |
|---|---|---|
| `onboarding` (shipped) | Merged | Provides the `brokerage_accounts` row this branch reads |
| KYC sync (in progress, other dev) | Active | Flips accounts to `ACTIVE` in prod; also likely builds reusable SSE consumer pattern we'll borrow for funding status |
| This branch — Plaid + ACH funding | Active | Depends on above for full prod value; fully self-contained in sandbox |
| Re-auth follow-up (next) | Not started | Depends on this branch for `PlaidService`, `FundingService` skeletons |
| SSE funding status consumer (later) | Not started | Depends on KYC sync branch's SSE infra pattern |

---

## Test Plan

### Unit tests
- `test_encryption.py` — Fernet round-trip; decrypt with secondary key (rotation); garbage ciphertext raises cleanly
- `test_plaid_service.py` — each method calls Plaid with expected payload; errors map to clean exceptions
- `test_funding_service.py`:
  - `link_bank` orchestration — mock Plaid (exchange + processor) + Alpaca (ACH create); verify DB writes in order, access_token encrypted on save
  - `link_bank` idempotency — second call with same `public_token` / `item_id` returns existing relationship
  - `link_bank` when brokerage account not `ACTIVE` — raises `ConflictError` before hitting any external API
  - `create_transfer` — payload construction (includes `transfer_type`, `timing`); returns Alpaca response
  - `unlink_bank` — calls Alpaca DELETE, soft-deletes row, doesn't touch `plaid_items`
  - `list_ach_relationships` — filters out `CANCELED`
  - `list_transfers` — merges local bank nickname onto Alpaca records

### Integration tests (against mocked Plaid + Alpaca)
- `POST /v1/funding/link-token` — returns token from Plaid mock
- `POST /v1/funding/link-bank` — happy path creates `plaid_items` + `ach_relationships` rows; access_token is encrypted in DB
- `POST /v1/funding/link-bank` — duplicate `public_token` returns existing; 200 not 409
- `POST /v1/funding/link-bank` — brokerage account not active → structured error
- `GET /v1/funding/ach-relationships` — excludes canceled
- `DELETE /v1/funding/ach-relationships/{id}` — soft-deletes, not queryable via list
- `POST /v1/funding/transfers` — sends `timing: "immediate"` + `transfer_type: "ach"` to Alpaca
- `GET /v1/funding/transfers` — merges nickname even when relationship is canceled
- All endpoints — 401 without JWT

### Verification steps before merging
1. `make test` — full suite green, no regressions
2. `uv run alembic heads` — single head (no migration conflict since we add none)
3. Manual sandbox E2E using `/sandbox/public_token/create` shortcut (bypasses Plaid Link UI): mint → exchange → processor → ACH → deposit → verify
4. Grep confirms no `plaid_access_token` logged in plaintext anywhere (check middleware + structlog config)

---

## File Summary (Backend)

Create: 11 files  
Modify: 3 files (`app/config.py`, `app/services/alpaca_broker.py`, `app/main.py`) + `.env.example`  
No migrations.

## File Summary (Frontend)

Create: ~10 views + viewmodel + 1 service wrapper + DTOs  
Delete: 3 placeholder files  
Modify: `HomeView` (wire the menu button) + any shared navigation container
