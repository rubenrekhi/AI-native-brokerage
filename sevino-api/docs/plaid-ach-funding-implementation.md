# Plaid + ACH Funding — Phased Backend Implementation Plan

> Companion to `docs/plaid-ach-funding-plan.md` (what ships / what doesn't) and
> `docs/plaid-integration.md` + `docs/alpaca-integration.md` (canonical tech refs).
>
> Branch: `tharsihanariyanayagam/plaid-ach-funding`
>
> Audience: the implementer. Open Phase 1 and work top-to-bottom. Each phase ends in a
> verifiable state — you can pause after any phase, run the verification, and come
> back later without half-built code in the tree.

---

## Decisions (Locked)

Open questions from the initial plan have been resolved. Recorded here so the
implementer doesn't re-litigate during build.

1. **Transfer amount bounds.** Pydantic: `Decimal`, `gt=0`, `max_digits=12`,
   `decimal_places=2`. No app-level ceiling. Alpaca's `422` (min $1 /
   broker-level caps) surfaces verbatim to iOS.
2. **Institution metadata origin.** Trust client-supplied `institution_name`
   / `account_mask` / `account_name` from Plaid Link's `onSuccess` metadata.
   Display-only values — no authoritative server-side refetch from
   `/institutions/get_by_id` or `/accounts/get`.
3. **Account-status pre-check.** Single code `ACCOUNT_NOT_ACTIVE` covers both
   "no brokerage_accounts row" and "row exists but status != ACTIVE." iOS
   routes both to the same "finish setting up your brokerage account" screen.
   No `detail.reason` branching — per product: it's technically impossible to
   reach Settings → Link Bank without having submitted KYC, so the no-row
   case is defensive-only and shouldn't surface to real users.
4. **`link-bank` idempotency — DB-level.** `UNIQUE(plaid_item_id)` on
   `plaid_items` is landed as a **separate prep PR before Phase 1** of this
   branch — not as part of Phase 4. Rationale: ships in isolation, trivial
   review, de-risks the Alembic head conflict with the KYC-sync branch before
   feature work starts. By the time the implementer reaches Phase 4, the
   constraint already exists in `main`. Defense in depth at the app layer:
   - Service layer does `PlaidItemRepository.get_by_plaid_item_id(...)` before
     calling Plaid step 4 — fast-path short-circuit for the common iOS
     network-retry case.
   - `IntegrityError` catch on insert closes the true-race window. Re-read
     the row and return the existing relationship.
5. **Transfer list pagination.** Pass-through `limit` (default 50, max 100)
   and `offset` to Alpaca. No server-side cross-page merging.
6. **`DELETE` semantics.** Call Alpaca `DELETE` first. On 2xx or 404,
   soft-delete locally (`status = 'CANCELED'`). On 5xx, surface
   `ALPACA_UNAVAILABLE` and leave the row untouched.
7. **Rate limit on `/v1/funding/*`.** Inherit the global per-user default
   (`120/minute` across all endpoints combined, keyed by user ID via
   `get_user_or_ip` in `app/rate_limit.py`). No per-endpoint overrides.
   Revisit `/link-token` specifically if we see abuse signal.

---

## Collision Map with KYC-Sync Branch

Files the other dev is modifying; do not touch in this branch:

- `app/worker.py`
- `app/tasks/` (entire directory)
- `app/repositories/brokerage_account.py`

Read-only consumption is fine — `FundingService` calls
`BrokerageAccountRepository.get_by_user_id(...)` to gate `link-bank` on
`account_status == "ACTIVE"`. That existing method is safe to call; we add no
new methods to that repo.

Also flag: both branches will touch `app/main.py` (router mounts) and
`app/config.py` (env vars). Merge conflicts there are trivial (different lines)
but expect them.

This branch itself ships **no Alembic migrations**. The one schema change it
needs (`UNIQUE(plaid_item_id)`) lands in a separate prep PR before Phase 1 —
see the "Prep PR" section below. The KYC-sync branch may still add its own
migrations; coordinate with that dev so your prep PR merges before they cut
theirs, and they chain off your head.

---

## Prep PR — `UNIQUE(plaid_item_id)` Migration (Merged Separately Before Phase 1)

**Goal:** Add the `UNIQUE` constraint on `plaid_items.plaid_item_id` on
`main` as a standalone PR before feature work starts.

**Why separate:**

- `plaid_items` is empty in every environment (bank linking hasn't shipped
  yet), so the constraint applies instantly with no backfill or duplicate
  cleanup required.
- Tiny PR (one migration file), trivial review, no business logic to debate.
- Once merged, the Alembic head conflict with the KYC-sync branch is resolved
  before it starts — the KYC-sync dev rebases their in-flight migration's
  `down_revision` onto this head and moves on.

**Files modified:**

- **NEW** `migrations/versions/<timestamp>_add_unique_plaid_item_id.py` —
  single Alembic migration. `upgrade()` adds the `UNIQUE` constraint,
  `downgrade()` drops it. Hand-write or generate via
  `make migration msg="add unique plaid_item_id"` and hand-trim to contain
  only the constraint add/drop.

**Verification:**

```bash
make infra && make migrate          # applies cleanly
uv run alembic heads                # exactly one head
uv run alembic downgrade -1         # reverses cleanly
make migrate                        # re-applies
uv run pytest                       # full suite still green
```

Also sanity-check in psql:

```bash
psql "$DATABASE_URL_DIRECT" -c "\d plaid_items"
# Expect: 'plaid_item_id' column now listed under "Indexes:" with `UNIQUE`
```

**Done looks like:** PR merged to `main`. `alembic heads` on `main` shows
one head. Feature branch (`tharsihanariyanayagam/plaid-ach-funding`) can
now be rebased onto `main` and Phase 1 begins against a schema that already
has the constraint.

---

## Phase 1 — Config + Encryption Helper

**Goal:** Land the `MultiFernet` encrypt/decrypt helper and the
`PLAID_FERNET_KEY` env plumbing. No new behavior in the app; pure infrastructure
we can unit-test in isolation.

**Files modified:**

- **NEW** `app/services/encryption.py`
- `app/config.py` — add `plaid_fernet_key: str = ""`, add a computed
  `plaid_fernet_keys` property that splits on comma and strips whitespace
- `.env.example` — add `PLAID_FERNET_KEY=` placeholder + one-line comment about
  comma-separated rotation
- **NEW** `tests/unit/test_encryption.py`

**Skeleton — `app/services/encryption.py`:**

```python
"""Application-level symmetric encryption for sensitive strings at rest.

Used to encrypt Plaid access tokens before persisting to `plaid_items.plaid_access_token`.
Key rotation is supported by passing a comma-separated list of Fernet keys in the
`PLAID_FERNET_KEY` env var: the first key is used for encryption, all keys are
tried on decrypt. See Phase 1 of `docs/plaid-ach-funding-implementation.md`.
"""

from cryptography.fernet import MultiFernet


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


def get_fernet() -> MultiFernet: ...


def encrypt(plaintext: str) -> str: ...


def decrypt(ciphertext: str) -> str: ...
```

**Dependencies:** none. `cryptography` already in `pyproject.toml`.

**Verification:**

```bash
# Generate a pair of dev keys for your local .env:
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Put that value (or two, comma-separated) in PLAID_FERNET_KEY in .env

uv run pytest tests/unit/test_encryption.py -v
```

Tests must cover:

- Round-trip (encrypt → decrypt → equals original)
- Rotation: encrypt with key-A, then re-init MultiFernet with `[key-B, key-A]`
  and successfully decrypt the old ciphertext
- Garbage ciphertext raises a clean `EncryptionError` (not a raw
  `InvalidToken`)
- Empty / missing `PLAID_FERNET_KEY` raises a clear startup error when
  `get_fernet()` is first called

**Done looks like:** `uv run pytest tests/unit/test_encryption.py` is green.
`grep -r "plaid_access_token" app/` shows no plaintext logging added. The
helper is importable but unused by the rest of the app.

**KYC-sync collision:** minor — both branches edit `app/config.py`. Merge
conflict will be on adjacent lines only.

---

## Phase 2 — PlaidService (External Client)

**Goal:** Thin async wrapper over `plaid-python` for the three calls we need.
Stateless, mockable, side-effect-free apart from network IO.

**Files modified:**

- **NEW** `app/services/plaid.py`
- **NEW** `tests/unit/test_plaid_service.py`
- **NEW** `tests/fixtures/mock_responses/plaid_link_token.json`
- **NEW** `tests/fixtures/mock_responses/plaid_exchange.json`
- **NEW** `tests/fixtures/mock_responses/plaid_processor_token.json`

**Skeleton — `app/services/plaid.py`:**

```python
"""Plaid REST API wrapper — link token mint, public-token exchange, processor token create.

One service method per upstream call. No orchestration here; that lives in
`app/services/funding.py`. Errors bubble up as `PlaidServiceError`; the caller
decides how to map them.

Canonical ref: docs/plaid-integration.md §§ Step 1, Step 3, Step 4.
"""

from typing import Any

import plaid
from plaid.api import plaid_api


class PlaidServiceError(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


class PlaidService:
    def __init__(self) -> None: ...

    async def create_link_token(self, *, user_id: str) -> str:
        """Step 1 — POST /link/token/create. Returns `link_token`."""

    async def exchange_public_token(
        self, *, public_token: str
    ) -> tuple[str, str]:
        """Step 3 — POST /item/public_token/exchange. Returns `(access_token, item_id)`."""

    async def create_processor_token(
        self, *, access_token: str, account_id: str
    ) -> str:
        """Step 4 — POST /processor/token/create with `processor=alpaca`.
        Returns `processor_token`."""
```

Implementation notes for the implementer (do not expand inline):

- `plaid-python` is sync; wrap blocking calls via
  `asyncio.to_thread(...)` or `anyio.to_thread.run_sync(...)`.
- Env selection: `settings.plaid_env` ∈ `{"sandbox", "production"}` →
  `plaid.Environment.Sandbox` / `.Production`. Reject `"development"` with a
  clear config error at init time.
- Map `plaid.ApiException` → `PlaidServiceError` with code taken from Plaid's
  `error_code` (e.g. `INVALID_CREDENTIALS`) and message from
  `display_message or error_message`.

**Dependencies:** Phase 1 (not strictly required; Plaid service holds no
tokens). Realistically: none.

**Verification:**

```bash
uv run pytest tests/unit/test_plaid_service.py -v
```

Tests (all with `plaid_api.PlaidApi` mocked):

- `create_link_token` sends expected payload (`products=["auth"]`,
  `country_codes=["US"]`, `client_name="Sevino"`, `user.client_user_id=<uuid>`)
- `exchange_public_token` parses `access_token` + `item_id` from response
- `create_processor_token` sends `processor="alpaca"` and parses `processor_token`
- Plaid API exception → `PlaidServiceError` with mapped code

**Done looks like:** unit tests green; service is importable; no wiring in
`main.py` or lifespan yet.

**KYC-sync collision:** none.

---

## Phase 3 — AlpacaBrokerService Funding Extensions

**Goal:** Add 5 methods to the existing `AlpacaBrokerService` for ACH
relationships and transfers. Reuses `_request`, token cache, and error mapping
already in place (see `app/services/alpaca_broker.py:99-140`).

**Files modified:**

- `app/services/alpaca_broker.py` — add 5 methods (no other changes)
- **NEW** `tests/unit/test_alpaca_broker_funding.py`
- **NEW** `tests/fixtures/mock_responses/alpaca_ach_relationship.json`
- **NEW** `tests/fixtures/mock_responses/alpaca_transfer.json`

**New method signatures (append after `update_account`):**

```python
async def create_ach_relationship(
    self, account_id: str, *, processor_token: str
) -> dict[str, Any]:
    """POST /v1/accounts/{id}/ach_relationships — body: {processor_token}."""

async def list_ach_relationships(self, account_id: str) -> list[dict[str, Any]]:
    """GET /v1/accounts/{id}/ach_relationships."""

async def delete_ach_relationship(
    self, account_id: str, relationship_id: str
) -> None:
    """DELETE /v1/accounts/{id}/ach_relationships/{rel_id}.
    204 → None. 404 → NotFoundError (already handled in _handle_response)."""

async def create_transfer(
    self,
    account_id: str,
    *,
    relationship_id: str,
    amount: str,
    direction: str,
) -> dict[str, Any]:
    """POST /v1/accounts/{id}/transfers.
    Always sends transfer_type="ach", timing="immediate".
    `direction` ∈ {"INCOMING", "OUTGOING"} — validated upstream in the schema."""

async def list_transfers(
    self,
    account_id: str,
    *,
    direction: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """GET /v1/accounts/{id}/transfers. Pagination pass-through to Alpaca."""
```

Implementation notes:

- `_request` returns parsed JSON on 200/201. Handle 204 (DELETE) by teaching
  `_handle_response` to return `{}` for 204, OR call `self._client.request(...)`
  directly in `delete_ach_relationship` and branch on status. Prefer the former
  (one-line change, benefits future endpoints).
- All 5 methods use `await self._request(...)`. Errors already map to
  `AlpacaBrokerError` / `AlpacaBrokerUnavailableError` / `NotFoundError`.

**Dependencies:** none (Phase 2 independent).

**Verification:**

```bash
uv run pytest tests/unit/test_alpaca_broker_funding.py -v
```

Tests use `httpx.MockTransport` (or patch `self._client`) per the existing
`test_alpaca_broker.py` pattern:

- `create_ach_relationship` → POSTs to correct path, body matches spec from
  `docs/plaid-integration.md` § Step 5
- `create_transfer` → body contains `transfer_type: "ach"`, `timing: "immediate"`,
  echoes `amount`/`direction`/`relationship_id`
- `list_transfers` with `direction="INCOMING"`, `limit=25` → query string
  correct
- `delete_ach_relationship` → 204 returns cleanly, no exception
- 404 from any endpoint → `NotFoundError`
- 409 from `create_ach_relationship` → `AlpacaBrokerError(status_code=409)`

**Done looks like:** unit tests green. Lifespan-installed
`app.state.alpaca` now has the new methods. No routes call them yet.

**KYC-sync collision:** possible — the other dev may also be editing
`alpaca_broker.py` (adding account status fetch or SSE helpers). Land first if
possible; otherwise expect merge conflict in the method-list section.

---

## Phase 4 — Repositories

**Goal:** Data-access layer for `plaid_items` and `ach_relationships`,
including encrypt/decrypt of `plaid_access_token` inside the Plaid repo.
Assumes the prep PR (above) has already landed the
`UNIQUE(plaid_item_id)` constraint on `main`.

**Files modified:**

- **NEW** `app/repositories/plaid_item.py`
- **NEW** `app/repositories/ach_relationship.py`
- **NEW** `tests/integration/test_plaid_item_repository.py`
- **NEW** `tests/integration/test_ach_relationship_repository.py`

**Skeleton — `app/repositories/plaid_item.py`:**

```python
"""Data access for `plaid_items`. Owns encrypt/decrypt of `plaid_access_token`.

Plaintext access tokens exist only in-memory inside this module and the
FundingService layer. They are encrypted via `app.services.encryption` on the
way in and decrypted on the way out. Never log the plaintext value.
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plaid_item import PlaidItem


class PlaidItemRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        plaid_item_id: str,
        plaid_access_token_plaintext: str,
        plaid_account_id: str,
        institution_name: str | None = None,
        account_mask: str | None = None,
        account_name: str | None = None,
    ) -> PlaidItem:
        """Encrypts `plaid_access_token_plaintext` before insert."""

    @staticmethod
    async def get_by_id(
        db: AsyncSession, item_pk: uuid.UUID
    ) -> PlaidItem | None: ...

    @staticmethod
    async def get_by_plaid_item_id(
        db: AsyncSession, plaid_item_id: str
    ) -> PlaidItem | None:
        """Idempotency lookup for `link-bank` retries."""

    @staticmethod
    async def get_access_token_plaintext(
        db: AsyncSession, item_pk: uuid.UUID
    ) -> str | None:
        """Decrypt and return. Returns None if the row is missing."""

    @staticmethod
    async def mark_inactive(
        db: AsyncSession, item_pk: uuid.UUID
    ) -> None: ...
```

**Skeleton — `app/repositories/ach_relationship.py`:**

```python
"""Data access for `ach_relationships`. Soft-delete only; never hard-delete.

See docs/plaid-integration.md § "Transfer History & Unlinking" for the rationale.
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ach_relationship import AchRelationship


class AchRelationshipRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        brokerage_account_id: uuid.UUID,
        plaid_item_id: uuid.UUID | None,
        alpaca_relationship_id: str,
        institution_name: str | None,
        account_mask: str | None,
        account_type: str | None,
        nickname: str | None,
        status: str = "QUEUED",
    ) -> AchRelationship: ...

    @staticmethod
    async def get_by_id(
        db: AsyncSession, rel_pk: uuid.UUID
    ) -> AchRelationship | None: ...

    @staticmethod
    async def get_by_alpaca_id(
        db: AsyncSession, alpaca_relationship_id: str
    ) -> AchRelationship | None:
        """Merge helper for GET /v1/funding/transfers."""

    @staticmethod
    async def list_active_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[AchRelationship]:
        """Excludes rows where status = 'CANCELED'."""

    @staticmethod
    async def list_all_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[AchRelationship]:
        """Includes canceled. Used when merging transfer history display names."""

    @staticmethod
    async def mark_canceled(
        db: AsyncSession, rel_pk: uuid.UUID
    ) -> None: ...
```

**Dependencies:** Phase 1 (encryption helper) + Prep PR merged and applied
locally.

**Verification:**

```bash
make infra   # if not already running
make migrate # applies prep-PR constraint if not already applied

# Repository tests:
uv run pytest tests/integration/test_plaid_item_repository.py tests/integration/test_ach_relationship_repository.py -v
```

Tests must cover:

- Round-trip: `create(...)` stores ciphertext in DB; raw SQL query on
  `plaid_access_token` column returns something that is NOT the plaintext;
  `get_access_token_plaintext` returns the original plaintext
- `get_by_plaid_item_id` returns the row; unknown id returns `None`
- `list_active_for_user` excludes canceled rows
- `list_all_for_user` includes canceled rows
- `mark_inactive` / `mark_canceled` flip status without touching other fields
- No row is ever deleted (assert row count stable after soft-delete)
- **Unique constraint:** inserting a second `plaid_items` row with a
  `plaid_item_id` value that already exists raises
  `sqlalchemy.exc.IntegrityError`

**Done looks like:** integration tests green against a real local Postgres.
Running `SELECT plaid_access_token FROM plaid_items LIMIT 1;` in psql
returns a Fernet ciphertext string (starts with `gAAAA...`) — never a
plaintext `access-sandbox-...`.

**KYC-sync collision:** none. The prep PR already handled the migration
coordination.

---

## Phase 5 — FundingService (Orchestration)

**Goal:** The logic layer that orchestrates Plaid steps 3→4→5, builds
transfers, and runs soft-delete unlinks. All external calls and DB writes flow
through here.

**Files modified:**

- **NEW** `app/services/funding.py`
- **NEW** `tests/unit/test_funding_service.py`

**Skeleton — `app/services/funding.py`:**

```python
"""Funding orchestrator: bank linking (Plaid 3→4→5 + Alpaca ACH) and transfers.

Routes depend on this service only. The service is the only place that combines
PlaidService, AlpacaBrokerService, and the two repositories.

Canonical flow: docs/plaid-integration.md § "End-to-End Flow".
Soft-delete rule: docs/plaid-integration.md § "Transfer History & Unlinking".
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ach_relationship import AchRelationship
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.plaid import PlaidService


# Known values for plaid_items.status (free-form TEXT column for now)
PLAID_ITEM_STATUS_ACTIVE = "active"
PLAID_ITEM_STATUS_INACTIVE = "inactive"
PLAID_ITEM_STATUS_REQUIRES_REAUTH = "requires_reauth"  # reserved; reauth branch

# Alpaca relationship statuses we treat as "active" for listing
ACH_RELATIONSHIP_STATUS_CANCELED = "CANCELED"


class FundingService:

    @staticmethod
    async def create_link_token(
        *, plaid: PlaidService, user_id: uuid.UUID
    ) -> str: ...

    @staticmethod
    async def link_bank(
        db: AsyncSession,
        *,
        plaid: PlaidService,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        public_token: str,
        account_id: str,
        institution_name: str | None,
        account_mask: str | None,
        account_name: str | None,
        nickname: str | None,
    ) -> AchRelationship:
        """Orchestrate Plaid exchange (step 3) → processor token (step 4) →
        Alpaca ACH relationship (step 5). Idempotent on Plaid `item_id`."""

    @staticmethod
    async def list_active_ach_relationships(
        db: AsyncSession, *, user_id: uuid.UUID
    ) -> list[AchRelationship]: ...

    @staticmethod
    async def unlink_bank(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
    ) -> None:
        """DELETE at Alpaca first; on success, mark local row CANCELED.
        On Alpaca 404, treat as already-gone and still soft-delete (idempotent)."""

    @staticmethod
    async def create_transfer(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
        amount: Decimal,
        direction: str,
    ) -> dict: ...

    @staticmethod
    async def list_transfers(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        limit: int | None,
        offset: int | None,
    ) -> list[dict]:
        """Fetch fresh from Alpaca. Merge local nickname / mask onto each record
        by joining on `alpaca_relationship_id`. Never cache status locally."""
```

Implementation notes — all must be implemented:

- **Account-status gate** (before any external call): load
  `BrokerageAccountRepository.get_by_user_id(db, user_id)`. If `None` or
  `account_status != "ACTIVE"`, raise
  `ConflictError("Brokerage account not active", code="ACCOUNT_NOT_ACTIVE", detail={"account_status": ...})`.
  See Phase 7 for the exception-to-HTTP mapping if `code=` isn't yet a
  ConflictError kwarg — if not, add `detail={"code": "ACCOUNT_NOT_ACTIVE"}` and
  the global handler already forwards `detail`.
- **Idempotency on `link_bank` — two layers (Decision #4):**
  1. **Fast path.** After Plaid step 3 (`exchange_public_token` — safe to
     re-run, Plaid returns the same `access_token` / `item_id` for the same
     underlying item), look up
     `PlaidItemRepository.get_by_plaid_item_id(db, item_id)`. If present
     with an associated active `AchRelationship`, return that row and skip
     Plaid step 4 + Alpaca step 5 entirely. Catches the common iOS
     network-retry case.
  2. **Race-safe path.** On insert into `plaid_items`, catch
     `sqlalchemy.exc.IntegrityError` from the
     `UNIQUE(plaid_item_id)` constraint added in Phase 4. Roll back the
     session, re-read by `plaid_item_id`, return the existing relationship.
     Covers the true-concurrent case where two requests raced past the
     fast-path lookup.
- **Alpaca 409 on `create_ach_relationship`:** catch
  `AlpacaBrokerError` where `status_code == 409`, call
  `alpaca.list_ach_relationships(...)`, find the existing relationship by
  some key (likely `bank_account_number` suffix — the Alpaca response will
  include a `nickname` / `account_mask`), match to our local row or raise
  `ConflictError("Bank already linked", code="BANK_ALREADY_LINKED")`.
- **Transfer amount:** received as `Decimal` from the schema; convert to
  `str(amount)` for Alpaca (their API takes strings).
- **`list_transfers` merge:** call
  `AchRelationshipRepository.list_all_for_user` (includes canceled) and build a
  `{alpaca_relationship_id: {nickname, account_mask, institution_name}}` dict;
  attach to each Alpaca record under a `bank` key. Unknown relationship_ids
  pass through with `bank=None`.
- **No transactions wrapped manually** — rely on `get_db` auto-commit.

**Dependencies:** Phases 1–4.

**Verification:**

```bash
uv run pytest tests/unit/test_funding_service.py -v
```

Mock both `PlaidService` and `AlpacaBrokerService` with `AsyncMock`. Mock
repositories with `unittest.mock.patch`. Tests:

- `link_bank` happy path — verifies call order: `exchange` → `create_processor_token`
  → `alpaca.create_ach_relationship` → `PlaidItemRepository.create` →
  `AchRelationshipRepository.create`
- `link_bank` with existing `plaid_item_id` in DB (fast path) → no Plaid
  step 4 and no Alpaca call; returns existing `AchRelationship`
- `link_bank` race path — patch `PlaidItemRepository.create` to raise
  `IntegrityError` once; service re-reads and returns the existing row
  without re-calling Plaid or Alpaca
- `link_bank` when brokerage account is `SUBMITTED` → raises `ConflictError`
  with `code=ACCOUNT_NOT_ACTIVE`; no Plaid/Alpaca calls made
- `link_bank` when no brokerage row exists → same error, same code
- `link_bank` Alpaca 409 → raises `ConflictError(code=BANK_ALREADY_LINKED)`
- `create_transfer` — payload assembly correct; `Decimal("500.00")` → `"500.00"`
- `unlink_bank` — Alpaca called first, repo `mark_canceled` only after success
- `unlink_bank` with Alpaca 404 → still soft-deletes locally
- `unlink_bank` with Alpaca 5xx → raises `AlpacaBrokerUnavailableError`,
  repo NOT called
- `list_transfers` — merges `nickname` / `account_mask` onto records whose
  `alpaca_relationship_id` matches, including canceled relationships

**Done looks like:** all `test_funding_service.py` tests green. Nothing is
wired into FastAPI yet — no routes, no deps. `curl localhost:8000/v1/funding/...`
still 404s.

**KYC-sync collision:** low. Only shared touchpoint is reading
`BrokerageAccountRepository.get_by_user_id`, which is stable.

---

## Phase 6 — Schemas + Router (Defined, Not Yet Mounted)

**Goal:** Define Pydantic request/response models and the FastAPI router with
all 6 endpoints wired to `FundingService`. Router is NOT yet added to
`app/main.py` — tests mount it via a local sub-app so the real `/v1/funding/*`
stays 404 on the deployed app until Phase 7.

**Files modified:**

- **NEW** `app/schemas/funding.py`
- **NEW** `app/routes/funding.py`
- **NEW** `tests/integration/test_funding_routes.py`

**Skeleton — `app/schemas/funding.py`:**

```python
"""Pydantic models for /v1/funding/* endpoints."""

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LinkTokenResponse(BaseModel):
    link_token: str


class LinkBankRequest(BaseModel):
    public_token: str
    account_id: str  # Plaid `accounts[0].id` from onSuccess metadata
    institution_name: str | None = None
    account_mask: str | None = None
    account_name: str | None = None
    nickname: str | None = None


class AchRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alpaca_relationship_id: str
    institution_name: str | None
    account_mask: str | None
    account_type: str | None
    nickname: str | None
    status: str


class TransferRequest(BaseModel):
    relationship_id: uuid.UUID  # local AchRelationship PK, NOT Alpaca's
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    direction: Literal["INCOMING", "OUTGOING"]


class TransferResponse(BaseModel):
    """Pass-through Alpaca transfer record plus our merged `bank` metadata."""

    id: str
    status: str
    amount: str
    direction: str
    created_at: str
    bank: AchRelationshipResponse | None = None
    # plus any other pass-through Alpaca fields we want on the wire


class TransferListResponse(BaseModel):
    transfers: list[TransferResponse]
```

**Skeleton — `app/routes/funding.py`:**

```python
"""FastAPI router for /v1/funding/*.

Mounted in app/main.py in Phase 7. All endpoints require authentication via
`get_current_user`; rate-limited at the global per-user default from
`app/rate_limit.py`.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.schemas.funding import (
    AchRelationshipResponse,
    LinkBankRequest,
    LinkTokenResponse,
    TransferListResponse,
    TransferRequest,
    TransferResponse,
)
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.funding import FundingService
from app.services.plaid import PlaidService

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_alpaca(request: Request) -> AlpacaBrokerService:
    return request.app.state.alpaca


def get_plaid(request: Request) -> PlaidService:
    return request.app.state.plaid


@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    user_id: str = Depends(get_current_user),
    plaid: PlaidService = Depends(get_plaid),
) -> LinkTokenResponse: ...


@router.post("/link-bank", response_model=AchRelationshipResponse)
async def link_bank(
    body: LinkBankRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    plaid: PlaidService = Depends(get_plaid),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> AchRelationshipResponse: ...


@router.get("/ach-relationships", response_model=list[AchRelationshipResponse])
async def list_ach_relationships(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AchRelationshipResponse]: ...


@router.delete("/ach-relationships/{relationship_id}", status_code=204)
async def delete_ach_relationship(
    relationship_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> None: ...


@router.post("/transfers", response_model=TransferResponse)
async def create_transfer(
    body: TransferRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> TransferResponse: ...


@router.get("/transfers", response_model=TransferListResponse)
async def list_transfers(
    limit: int | None = None,
    offset: int | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    alpaca: AlpacaBrokerService = Depends(get_alpaca),
) -> TransferListResponse: ...
```

**Test strategy for un-mounted router:**

In `tests/integration/test_funding_routes.py`, build a local FastAPI app:

```python
# shape only — implementer fills in
from fastapi import FastAPI
from app.routes.funding import router as funding_router
from app.exceptions import register_exception_handlers
# plus dependency overrides identical to main app's

def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(funding_router, prefix="/v1/funding", tags=["funding"])
    register_exception_handlers(app)
    return app
```

Then use `AsyncClient(transport=ASGITransport(app=build_test_app()), ...)`
with the same auth / db override pattern as `tests/conftest.py`.

**Dependencies:** Phase 5.

**Verification:**

```bash
uv run pytest tests/integration/test_funding_routes.py -v
```

Tests:

- `POST /v1/funding/link-token` → 200, returns Plaid mock token
- `POST /v1/funding/link-bank` happy path → 200, creates rows, response shape matches
- `POST /v1/funding/link-bank` with `ACCOUNT_NOT_ACTIVE` → 409 with
  `{"code": "ACCOUNT_NOT_ACTIVE"}` in body
- `POST /v1/funding/link-bank` duplicate retry → 200 with existing row
- `GET /v1/funding/ach-relationships` → omits canceled
- `DELETE /v1/funding/ach-relationships/{id}` → 204; subsequent list omits it
- `POST /v1/funding/transfers` → verifies `transfer_type: "ach"` and
  `timing: "immediate"` flow through to Alpaca mock
- `GET /v1/funding/transfers` → returns merged `bank` nickname even for
  canceled relationship
- Every endpoint without JWT → 401 `AUTHENTICATION_ERROR`
- `POST /v1/funding/transfers` with `amount=-10` → 422 `VALIDATION_ERROR`

Also run:

```bash
# Confirm the real app still has no /v1/funding/* mounted:
uv run uvicorn app.main:app --port 8001 &
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/v1/funding/link-token
# Expect 404
kill %1
```

**Done looks like:** integration tests green; production app still 404s on
`/v1/funding/*`.

**KYC-sync collision:** none.

---

## Phase 7 — Wire Up: Lifespan, Main, PlaidService Singleton

**Goal:** Mount the router, construct `PlaidService` as a singleton on
`app.state.plaid` alongside `app.state.alpaca`, validate the end-to-end
dependency chain, ship.

**Files modified:**

- `app/lifecycle.py` — instantiate `PlaidService()` at startup, attach to
  `app.state.plaid`; add teardown only if `PlaidService` holds a client
  to close (plaid-python ApiClient does; call `api_client.close()`)
- `app/main.py` — `from app.routes.funding import router as funding_router`,
  `app.include_router(funding_router, prefix="/v1/funding", tags=["funding"])`
- `tests/integration/test_lifecycle.py` — if the file exists, extend to assert
  `app.state.plaid is not None`; otherwise skip

**Dependencies:** Phases 1–6.

**Verification:**

```bash
# Full unit + integration suite (no behavior regression):
make test

# Single alembic head:
cd sevino-api && uv run alembic heads
# Expect exactly one line

# App boots and funding routes are live:
uv run uvicorn app.main:app --port 8001 &
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-API-Key: $API_KEY" http://localhost:8001/v1/funding/link-token
# Expect 401 (auth required) — NOT 404

kill %1
```

**Done looks like:** `make test` green across the board. Hitting
`/v1/funding/link-token` with an API key but no JWT returns a 401 with
`{"error": "...", "code": "AUTHENTICATION_ERROR"}`. With both API key AND a
valid dev JWT, returns 200 with a Plaid link token.

**KYC-sync collision:** HIGH — both branches modify `app/main.py` and possibly
`app/lifecycle.py`. Coordinate merge order with the KYC-sync dev. Conflicts
should be mechanical (adjacent `include_router` / lifespan lines).

---

## Phase 8 — Manual Sandbox E2E Verification

**Goal:** End-to-end smoke against real Plaid + Alpaca sandbox environments,
using Plaid's `/sandbox/public_token/create` to bypass the Link UI. This
validates the full path that the iOS client will exercise.

**Files modified:** none (verification phase only).

**Dependencies:** Phases 1–7 all merged / applied locally.

**Setup preconditions:**

- Local `.env` has real Plaid sandbox `PLAID_CLIENT_ID` / `PLAID_SECRET` and
  Alpaca sandbox keys
- A dev user exists with a `brokerage_accounts` row whose `account_status =
  'ACTIVE'` (in sandbox this usually happens automatically within seconds of
  KYC submission — if your local user is stuck in `SUBMITTED`, fix by direct
  SQL update for the smoke test)
- You have a valid Supabase JWT for that user (grab from the iOS app or from a
  Supabase test token)

**Verification script (copy-pasteable):**

```bash
# 0) Set up vars
export API_KEY="<from .env>"
export JWT="<valid supabase access token for the dev user>"
export PLAID_CLIENT_ID="<from .env>"
export PLAID_SECRET="<from .env>"

# 1) Start server
make server &
SERVER_PID=$!
sleep 3

# 2) Mint a sandbox public_token WITHOUT opening Plaid Link UI
#    (bypasses Steps 1 + 2 from docs/plaid-integration.md)
curl -s -X POST https://sandbox.plaid.com/sandbox/public_token/create \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"institution_id\":\"ins_109508\",\"initial_products\":[\"auth\"]}" \
  | tee /tmp/plaid_sandbox.json
export PUBLIC_TOKEN=$(python3 -c "import json; print(json.load(open('/tmp/plaid_sandbox.json'))['public_token'])")

# 3) Grab the account_id by exchanging + listing accounts on the Plaid side
#    (in real flow the iOS SDK provides this — we fetch it manually for the smoke test)
curl -s -X POST https://sandbox.plaid.com/item/public_token/exchange \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"public_token\":\"$PUBLIC_TOKEN\"}" \
  | tee /tmp/plaid_exchange.json
export ACCESS_TOKEN=$(python3 -c "import json; print(json.load(open('/tmp/plaid_exchange.json'))['access_token'])")
curl -s -X POST https://sandbox.plaid.com/accounts/get \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS_TOKEN\"}" \
  | tee /tmp/plaid_accounts.json
export ACCOUNT_ID=$(python3 -c "import json; print(json.load(open('/tmp/plaid_accounts.json'))['accounts'][0]['account_id'])")

# IMPORTANT: we just burned the $PUBLIC_TOKEN in step 3's exchange — regenerate one
#            to send to our own /link-bank. (Public tokens are one-time-use.)
curl -s -X POST https://sandbox.plaid.com/sandbox/public_token/create \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"institution_id\":\"ins_109508\",\"initial_products\":[\"auth\"]}" \
  | tee /tmp/plaid_sandbox2.json
export PUBLIC_TOKEN=$(python3 -c "import json; print(json.load(open('/tmp/plaid_sandbox2.json'))['public_token'])")
# Note: the fresh public token maps to a DIFFERENT account_id. Re-run step 3's
# /accounts/get against the new access_token if you want to link the "real" one,
# OR skip the detour entirely and just pass the new account_id from the
# sandbox response metadata. For a smoke test, any valid account works.

# 4) Call our backend: link-token → link-bank → transfer
curl -s -X POST http://localhost:8000/v1/funding/link-token \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT"
# Expect: {"link_token": "link-sandbox-..."}

curl -s -X POST http://localhost:8000/v1/funding/link-bank \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d "{\"public_token\":\"$PUBLIC_TOKEN\",\"account_id\":\"$ACCOUNT_ID\",\"institution_name\":\"First Platypus Bank\",\"account_mask\":\"0000\",\"nickname\":\"Test Checking\"}" \
  | tee /tmp/link_bank.json
export REL_ID=$(python3 -c "import json; print(json.load(open('/tmp/link_bank.json'))['id'])")
# Expect: 200, body contains alpaca_relationship_id and status in {QUEUED, APPROVED}

curl -s http://localhost:8000/v1/funding/ach-relationships \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT"
# Expect: list with one entry

curl -s -X POST http://localhost:8000/v1/funding/transfers \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d "{\"relationship_id\":\"$REL_ID\",\"amount\":\"500.00\",\"direction\":\"INCOMING\"}"
# Expect: 200, status=QUEUED

curl -s http://localhost:8000/v1/funding/transfers \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT"
# Expect: one record, bank.nickname="Test Checking"

# 5) Unlink and re-verify
curl -s -X DELETE http://localhost:8000/v1/funding/ach-relationships/$REL_ID \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT" \
  -o /dev/null -w "%{http_code}\n"
# Expect: 204

curl -s http://localhost:8000/v1/funding/ach-relationships \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT"
# Expect: empty list

curl -s http://localhost:8000/v1/funding/transfers \
  -H "X-API-Key: $API_KEY" -H "Authorization: Bearer $JWT"
# Expect: the transfer from step 4 STILL APPEARS with bank.nickname populated
#         (historical transfer + canceled relationship merge)

# 6) No plaintext access tokens in logs
grep -ri "access-sandbox-" logs/ || echo "no plaintext token leaked"
# (adjust log path to wherever the dev server writes; check stdout too)

# 7) Stop server
kill $SERVER_PID
```

**Done looks like:**

- All seven curl assertions above match their `# Expect:` lines
- The final `grep` finds no plaintext `access-sandbox-...` strings anywhere in
  logs or stdout capture
- `uv run alembic heads` still shows one head
- A quick peek at `plaid_items` in Supabase Studio shows the
  `plaid_access_token` column contains a `gAAAA...` Fernet blob, not a
  plaintext `access-sandbox-...` string

**KYC-sync collision:** none (verification-only phase).

---

## Branch Acceptance Checklist

Before opening the PR for review:

- [ ] `make test` fully green (unit + integration, no skips introduced by this branch)
- [ ] `uv run alembic heads` returns exactly one head
- [ ] Phase 8 manual E2E completed and recorded in PR description
- [ ] `grep -rn "access-sandbox-\|access-production-" app/ tests/` returns nothing
- [ ] `grep -rn "plaid_access_token" app/` shows only repository/encryption
      code paths — no logging, no schema fields, no response models
- [ ] No new files touched under `app/worker.py`, `app/tasks/`, or
      `app/repositories/brokerage_account.py`
- [ ] PR description cross-references `docs/plaid-ach-funding-plan.md` scope
      section and explicitly lists the deferred items (SSE, re-auth, webhooks,
      micro-deposit) as NOT in this branch
