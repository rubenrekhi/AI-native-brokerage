# scripts/

Developer tooling. Not loaded by the app at runtime. Not run in CI.

## Funding smoke tests

End-to-end sanity checks for the `/v1/funding/*` stack against **real** Plaid
and Alpaca sandbox environments. Exercise the flows an iOS client would drive.

Use them:

- Before merging a PR that touches `app/services/funding.py`,
  `app/services/plaid.py`, `app/services/alpaca_broker.py` (funding methods),
  or any of the `/v1/funding/*` routes.
- When reproducing an iOS-reported funding issue from the shell.
- As live contract tests — if Plaid or Alpaca change a response shape, these
  catch it; unit tests with mocked responses will not.

### One-time prerequisites

1. Real Plaid sandbox credentials in `.env`:
   - `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV=sandbox`
2. Real Alpaca sandbox credentials in `.env`:
   - `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
3. `PLAID_FERNET_KEY` in `.env` (any valid Fernet key works for local dev).
   Generate one with:
   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. `make infra` running (local Supabase + Redis).
5. `make migrate` has been applied.

### The scripts

| Script | Covers | Runtime | Requires |
|---|---|---|---|
| `funding_smoke.sh` | Happy-path link-bank → deposit → list → unlink → historical display. Plus DB-level ciphertext assertion and 409 BANK_ALREADY_LINKED. | ~15s | `seed_funding_sandbox.py` |
| `funding_withdraw_smoke.sh` | OUTGOING transfer E2E. Does a deposit, waits up to 30 min for settlement, then withdraws. | Up to 30 min | `seed_funding_sandbox.py` |
| `funding_errors_smoke.sh` | ACCOUNT_NOT_ACTIVE gate. Flips `brokerage_accounts.account_status` to SUBMITTED, verifies both `POST /link-bank` and `GET /transfers` 409 with the right code + detail, restores status. | ~2s | `seed_funding_sandbox.py` |

### Running them

Two terminals:

```bash
# Terminal 1
make server

# Terminal 2 — seed once, then run any/all smokes
uv run python scripts/seed_funding_sandbox.py
source scripts/.funding_smoke_env

bash scripts/funding_smoke.sh                      # full happy + 409 + DB ciphertext
bash scripts/funding_smoke.sh --skip-unlink        # leave bank linked + deposit pending
bash scripts/funding_errors_smoke.sh               # quick — error-path gate
bash scripts/funding_withdraw_smoke.sh             # slow — waits for settlement
bash scripts/funding_withdraw_smoke.sh --assume-settled  # if you've already waited
```

Each script ends in a green "PASSED" line on success and exits non-zero on
any failure.

### Re-seeding

`seed_funding_sandbox.py` is idempotent. Re-run it whenever:

- Your JWT expired (Supabase access tokens live ~1 hour).
- You want a fresh Alpaca sandbox account (the seed always creates one — see
  note below).
- Local Postgres state drifted.

It always creates a fresh Alpaca sandbox account rather than reusing, because
Alpaca sandbox caps 1 ACH transfer per direction per trading day per account.
Reusing would block the smoke's deposit step after the first run of the day.

### State created

Running the seed creates:

- One row in `auth.users` (`funding-smoke@sevino.test`). Reused across runs.
- One row in `user_profiles`. Reused.
- One row in `brokerage_accounts`, rebound each run to a fresh Alpaca
  sandbox account. Status `ACTIVE`.
- A new brokerage account at Alpaca sandbox per run (old ones orphaned — fine
  for sandbox).

Running the main smoke creates:

- One `plaid_items` row per run (encrypted access token).
- One `ach_relationships` row per run. Canceled at end unless `--skip-unlink`.
- One ACH relationship + one $500 deposit at Alpaca sandbox per run.
  Canceled/historical at end unless `--skip-unlink`.

### Why these aren't in CI

- Hit external services (Plaid + Alpaca) with real credentials — secret
  management + rate limits make them awkward to automate
- Sandbox outages happen; flaky CI is worse than no CI
- Each run leaves real state at Alpaca — fine for manual, messy for CI
- The "runs every PR" slot belongs to future XCUITest / Playwright against
  **staging**, not sandbox

### Running against staging

The scripts take `BACKEND_URL` as an env var (default `http://localhost:8000`).
To run against the staging backend once it's set up for funding:

```bash
export BACKEND_URL=https://staging.sevino.ai
# plus a JWT for a staging user — seed script won't help you here since it
# writes to local Postgres. You'd need to mint/copy a staging JWT manually.
bash scripts/funding_smoke.sh
```

Note that Alpaca + Plaid are still sandbox in both environments.

### Files

- `seed_funding_sandbox.py` — idempotent seeder: auth.users + user_profiles +
  brokerage_accounts + Alpaca sandbox account + JWT. Writes
  `.funding_smoke_env`.
- `funding_smoke.sh` — happy path + ciphertext-at-rest + 409 duplicate.
- `funding_withdraw_smoke.sh` — OUTGOING transfer verification.
- `funding_errors_smoke.sh` — ACCOUNT_NOT_ACTIVE gate.
- `.funding_smoke_env` — seeder output. Contains a JWT. Git-ignored.
