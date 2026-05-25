#!/usr/bin/env bash
#
# Funding reconciliation cron smoke against real Alpaca sandbox (SEV-580).
# Verifies that app.tasks.reconcile_funding correctly observes drift between
# local `ach_relationships` and Alpaca state. Two scenarios:
#
#   A. Status drift  — local QUEUED, Alpaca APPROVED → cron flips local to APPROVED
#   B. Server-side cancellation — DELETE relationship at Alpaca directly (out of
#      band, so local row stays non-canceled) → cron marks local CANCELED
#
# Prerequisites (chain with the existing funding smoke setup):
#   1. `make infra` running
#   2. `uv run python scripts/seed_funding_sandbox.py`
#   3. `bash scripts/funding_smoke.sh --skip-unlink`   # creates a live link to reconcile
#   4. `source scripts/.funding_smoke_env`
#
# Usage:
#   bash scripts/funding_reconcile_smoke.sh

set -euo pipefail

# ---- required env (set by seed_funding_sandbox.py + .env) ----
: "${TEST_USER_ID:?Source scripts/.funding_smoke_env first}"
: "${ALPACA_ACCOUNT_ID:?Source scripts/.funding_smoke_env first}"

# ALPACA_API_KEY / ALPACA_SECRET_KEY come from .env, not the smoke env file.
ENV_FILE="$(dirname "$0")/../.env"
ALPACA_API_KEY=$(grep -E '^ALPACA_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
ALPACA_SECRET_KEY=$(grep -E '^ALPACA_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
: "${ALPACA_API_KEY:?ALPACA_API_KEY missing from .env}"
: "${ALPACA_SECRET_KEY:?ALPACA_SECRET_KEY missing from .env}"

PSQL_ARGS=(-tAX -h localhost -p 54322 -U postgres -d postgres)
export PGPASSWORD=postgres

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m--- %s ---\033[0m\n' "$*"; }
fail()  { red "FAIL: $*"; exit 1; }

# ---- helpers ----
get_alpaca_token() {
  curl -sS -X POST "https://authx.sandbox.alpaca.markets/v1/oauth2/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${ALPACA_API_KEY}&client_secret=${ALPACA_SECRET_KEY}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])"
}

# Reads the single active local relationship for TEST_USER_ID. Fails loudly if
# zero or multiple rows exist — the prereq smoke leaves exactly one.
# psql -tAX uses '|' as field separator; output: id|alpaca_id|status.
get_local_rel() {
  psql "${PSQL_ARGS[@]}" -c "
    SELECT id, alpaca_relationship_id, status
    FROM ach_relationships
    WHERE user_id='${TEST_USER_ID}' AND status != 'CANCELED'
  " > "$TMP/rel.tsv"
  local count
  count=$(wc -l < "$TMP/rel.tsv" | tr -d ' ')
  if [ "$count" != "1" ]; then
    fail "expected exactly 1 active local relationship, got $count. Run funding_smoke.sh --skip-unlink first."
  fi
}

run_cron() {
  # Direct invocation — bypass arq queue so the smoke is deterministic and
  # doesn't need a worker process running. ctx mirrors what worker.startup
  # builds at runtime: an AlpacaBrokerService on ctx["alpaca"].
  uv run python -c "
import asyncio
from app.services.alpaca_broker import AlpacaBrokerService
from app.tasks.reconcile_funding import reconcile_funding

async def main():
    alpaca = AlpacaBrokerService()
    try:
        result = await reconcile_funding({'alpaca': alpaca})
        print(f'  cron returned: {result}')
    finally:
        await alpaca.close()

asyncio.run(main())
"
}

# ---- 0. preflight ----
blue "0. preflight"
get_local_rel
REL_PK=$(cut -d'|' -f1 "$TMP/rel.tsv")
ALPACA_REL_ID=$(cut -d'|' -f2 "$TMP/rel.tsv")
INITIAL_STATUS=$(cut -d'|' -f3 "$TMP/rel.tsv")
green "  local rel: id=$REL_PK alpaca_id=$ALPACA_REL_ID status=$INITIAL_STATUS"

TOKEN=$(get_alpaca_token)

# Confirm Alpaca knows about it. If Alpaca already dropped it, scenario A is
# untestable — bail with a clear message rather than producing confusing output.
HTTP_STATUS=$(curl -sS -o "$TMP/alpaca_rels.json" -w "%{http_code}" \
  "https://broker-api.sandbox.alpaca.markets/v1/accounts/${ALPACA_ACCOUNT_ID}/ach_relationships" \
  -H "Authorization: Bearer $TOKEN")
[ "$HTTP_STATUS" = "200" ] || fail "Alpaca list returned $HTTP_STATUS: $(cat "$TMP/alpaca_rels.json")"

REMOTE_STATUS=$(python3 -c "
import json
rels = json.load(open('$TMP/alpaca_rels.json'))
for r in rels:
    if r['id'] == '$ALPACA_REL_ID':
        print(r['status'])
        break
")
if [ -z "$REMOTE_STATUS" ]; then
  fail "rel $ALPACA_REL_ID not present at Alpaca — re-run funding_smoke.sh --skip-unlink"
fi
green "  alpaca status: $REMOTE_STATUS"

# ---- A. status drift ----
blue "A. status drift — force local QUEUED, expect cron to flip to remote status"
psql "${PSQL_ARGS[@]}" -c "
  UPDATE ach_relationships SET status='QUEUED' WHERE id='$REL_PK'
" > /dev/null
green "  forced local → QUEUED"

run_cron

NEW_STATUS=$(psql "${PSQL_ARGS[@]}" -c "SELECT status FROM ach_relationships WHERE id='$REL_PK'" | tr -d ' ')
if [ "$NEW_STATUS" = "$REMOTE_STATUS" ] && [ "$NEW_STATUS" != "QUEUED" ]; then
  green "  ✓ local flipped QUEUED → $NEW_STATUS (matches Alpaca)"
elif [ "$REMOTE_STATUS" = "QUEUED" ]; then
  # Sandbox didn't auto-approve yet. Not a bug in our cron — skip with a note.
  red  "  SKIP: Alpaca still reports QUEUED in sandbox; can't observe drift this run"
else
  fail "expected local=$REMOTE_STATUS after reconcile, got $NEW_STATUS"
fi

# ---- B. server-side cancellation ----
blue "B. server-side cancellation — DELETE at Alpaca, expect cron to mark local CANCELED"

HTTP_STATUS=$(curl -sS -o "$TMP/del.json" -w "%{http_code}" -X DELETE \
  "https://broker-api.sandbox.alpaca.markets/v1/accounts/${ALPACA_ACCOUNT_ID}/ach_relationships/${ALPACA_REL_ID}" \
  -H "Authorization: Bearer $TOKEN")
case "$HTTP_STATUS" in
  204|200) green "  Alpaca DELETE → $HTTP_STATUS" ;;
  *) fail "Alpaca DELETE returned $HTTP_STATUS: $(cat "$TMP/del.json")" ;;
esac

# Sanity check: local row is still non-canceled (we DELETEd at Alpaca only).
LOCAL_BEFORE=$(psql "${PSQL_ARGS[@]}" -c "SELECT status FROM ach_relationships WHERE id='$REL_PK'" | tr -d ' ')
if [ "$LOCAL_BEFORE" = "CANCELED" ]; then
  fail "local already CANCELED before cron — test setup broken"
fi
green "  local before cron: $LOCAL_BEFORE (non-canceled as expected)"

run_cron

FINAL_STATUS=$(psql "${PSQL_ARGS[@]}" -c "SELECT status FROM ach_relationships WHERE id='$REL_PK'" | tr -d ' ')
[ "$FINAL_STATUS" = "CANCELED" ] || fail "expected local=CANCELED after server-side cancel, got $FINAL_STATUS"
green "  ✓ local marked CANCELED"

echo
green "ALL RECONCILE SMOKE CHECKS PASSED"
echo
echo "Note: this smoke leaves the local + Alpaca relationship in a canceled state."
echo "Re-run seed_funding_sandbox.py + funding_smoke.sh --skip-unlink to set up another."
