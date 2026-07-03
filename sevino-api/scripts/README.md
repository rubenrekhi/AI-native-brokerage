# scripts/

Developer tooling. Not loaded by the app at runtime. Not run in CI.

## AI loop smoke

Replaced by the pytest smoke harness at `tests/ai/smoke/` — see
`tests/ai/smoke/README.md`. Run with
`RUN_AI_SMOKE=1 uv run pytest tests/ai/smoke -v`.

## Daily Digest tools

### Dry-run a real user's digest

Runs the production digest assembly path for a user without writing a snapshot.
Requires local infrastructure plus real `FMP_API_KEY` and `ANTHROPIC_API_KEY`
in `.env`.

```bash
make digest-dry-run USER_EMAIL=user@example.com
# equivalent:
uv run python scripts/digest_dry_run.py --user-email user@example.com
```

The script prints the ordered digest cards as JSON to stdout and sends
progress/errors to stderr, so it can be piped through `jq`.

### Seed deterministic digest fixture data

`seed_digest.py` creates a local fixture user and verifies digest generation
without external Alpaca/FMP/Anthropic calls; provider inputs are in-memory
fixtures.

```bash
make infra
make migrate
uv run python scripts/seed_digest.py
```

## FMP / market-data rollout checks

`fmp_alpaca_parity_check.py` compares FMP bars against Alpaca bars for the
`FMP_BARS_ENABLED` rollout. Run it only in an environment with real production
market-data credentials; Alpaca sandbox data is synthetic and not useful for
parity.

```bash
uv run python scripts/fmp_alpaca_parity_check.py
```

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
| `funding_reauth_smoke.sh` | Plaid ITEM_LOGIN_REQUIRED reauth flow: links a sandbox item, forces reset_login, waits for webhook delivery, and verifies `requires_reauth=true`. | ~30s | `seed_funding_sandbox.py`, public `PLAID_WEBHOOK_URL` |
| `funding_reconcile_smoke.sh` | Funding reconciliation cron path: detects local/Alpaca status drift and out-of-band server-side ACH cancellation. | ~15s | `funding_smoke.sh --skip-unlink` |

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
bash scripts/funding_reauth_smoke.sh               # requires public PLAID_WEBHOOK_URL
bash scripts/funding_reconcile_smoke.sh            # after funding_smoke.sh --skip-unlink
```

Each script prints a green success line on success and exits non-zero on any
failure.

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
- `funding_reauth_smoke.sh` — Plaid reauth webhook verification.
- `funding_reconcile_smoke.sh` — direct funding reconciliation task verification.
- `.funding_smoke_env` — seeder output. Contains a JWT. Git-ignored.

## Stop-order smoke

End-to-end sanity check for stop orders (`type: "stop"`) against the **real**
Alpaca sandbox. Verifies what the mocked unit/integration tests cannot: that
sandbox accepts `type=stop` + `stop_price` + `time_in_force=gtc`, echoes
`stop_price` back (so the echo-sourced persistence is real), and what status a
resting stop reports.

Use it before merging anything that touches the order-placement path
(`app/schemas/trading.py`, `app/services/trading.py`, the stop_price plumbing).

### Prerequisites

1. Real Alpaca sandbox credentials in `.env` (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`).
2. `make infra` running.
3. A **funded** sandbox account that holds at least one whole share of a long
   equity (the sell stop protects it — no ACH settlement wait).

### Running

```bash
# Terminal 1
make server

# Terminal 2 — seed against your funded account, then run the smoke
uv run python scripts/seed_stop_sandbox.py <alpaca_account_id> [symbol]
source scripts/.stop_smoke_env
bash scripts/stop_order_smoke.sh              # sell + buy + wrong-side + list
```

The seed computes a resting sell-stop trigger at half the current price (so the
stop the smoke places never fires) and picks the first eligible long position if
`[symbol]` is omitted. If the account
is already linked in local Postgres (`brokerage_accounts.alpaca_account_id` is
unique), the seed authenticates as its existing owner via a Supabase admin
magic-link OTP exchange — no password change, no re-linking.

### Files

- `seed_stop_sandbox.py` — points a local user at an existing funded account,
  mints a JWT, picks a held position, writes `.stop_smoke_env`.
- `stop_order_smoke.sh` — sell stop, buy stop, wrong-side stop, and
  list-projection coverage; each placed order is canceled.
- `stop_trigger_fill_smoke.sh` — TRIGGER → FILL lifecycle (the SSE-handler
  path). Requires market hours + the worker running, and sells one real
  sandbox share.
- `.stop_smoke_env` — seeder output. Contains a JWT. Git-ignored.

## Portfolio iOS E2E seed

`seed_portfolio_e2e.py` links a local phone-OTP test user to an existing
Alpaca sandbox account so the iOS simulator can exercise holdings/portfolio
screens against real sandbox positions.

Prerequisites:

1. `make infra` running.
2. Real Alpaca sandbox credentials in `.env`.
3. An existing Alpaca sandbox account with positions.

Run:

```bash
uv run python scripts/seed_portfolio_e2e.py <alpaca_account_id>
```

Then sign in on the iOS simulator with phone `15551234567` and OTP `123456`
from the local Supabase `auth.sms.test_otp` config.
