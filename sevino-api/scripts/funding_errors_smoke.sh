#!/usr/bin/env bash
#
# Verify error paths on /v1/funding/* that the happy-path smoke doesn't touch.
# Currently covers:
#   - ACCOUNT_NOT_ACTIVE gate (brokerage account not yet activated)
#
# This script temporarily flips brokerage_accounts.account_status to SUBMITTED
# via psql, exercises the gate, then flips it back. Safe to re-run.
#
# Usage:
#   bash scripts/funding_errors_smoke.sh
#
# Prereqs: same as funding_smoke.sh — seed + source the env first.

set -euo pipefail

: "${JWT:?Source scripts/.funding_smoke_env first}"
: "${TEST_USER_ID:?}"
: "${BACKEND_URL:=http://localhost:8000}"

AUTH_HEADERS=(-H "Authorization: Bearer $JWT")
if [ -n "${API_KEY:-}" ]; then
  AUTH_HEADERS+=(-H "X-API-Key: $API_KEY")
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; restore_status' EXIT

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m--- %s ---\033[0m\n' "$*"; }
fail()  { red "FAIL: $*"; exit 1; }

psql_exec() {
  PGPASSWORD=postgres psql -tAX -h localhost -p 54322 -U postgres -d postgres -c "$1"
}

restore_status() {
  # Best-effort: always try to restore ACTIVE at exit, even on failure/ctrl-C.
  psql_exec "UPDATE brokerage_accounts SET account_status='ACTIVE' WHERE user_id='$TEST_USER_ID';" > /dev/null 2>&1 || true
}

# ---- capture original state ----
ORIGINAL_STATUS=$(psql_exec "SELECT account_status FROM brokerage_accounts WHERE user_id='$TEST_USER_ID';" | tr -d ' ')
[ -n "$ORIGINAL_STATUS" ] || fail "no brokerage row for $TEST_USER_ID — run seed_funding_sandbox.py first"
blue "captured original account_status = $ORIGINAL_STATUS"

# ---- test 1: ACCOUNT_NOT_ACTIVE when status = SUBMITTED ----
blue "1. flip account_status → SUBMITTED, expect 409 ACCOUNT_NOT_ACTIVE"
psql_exec "UPDATE brokerage_accounts SET account_status='SUBMITTED' WHERE user_id='$TEST_USER_ID';" > /dev/null

HTTP=$(curl -sS -X POST "$BACKEND_URL/v1/funding/link-bank" \
  "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
  -d '{"public_token":"ignored","account_id":"ignored"}' \
  -o "$TMP/resp.json" -w "%{http_code}")
CODE=$(python3 -c "import json; print(json.load(open('$TMP/resp.json')).get('code',''))")
STATUS_DETAIL=$(python3 -c "
import json
d = json.load(open('$TMP/resp.json'))
detail = d.get('detail') or {}
print(detail.get('account_status'))
")
if [ "$HTTP" = "409" ] && [ "$CODE" = "ACCOUNT_NOT_ACTIVE" ] && [ "$STATUS_DETAIL" = "SUBMITTED" ]; then
  green "  409 ACCOUNT_NOT_ACTIVE + detail.account_status=SUBMITTED ✓"
else
  fail "expected 409 ACCOUNT_NOT_ACTIVE detail.account_status=SUBMITTED; got HTTP=$HTTP code=$CODE status=$STATUS_DETAIL body=$(cat "$TMP/resp.json")"
fi

# ---- test 2: also gated when fetching transfers (defense in depth) ----
blue "2. GET /v1/funding/transfers while SUBMITTED → still 409 ACCOUNT_NOT_ACTIVE"
HTTP=$(curl -sS "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" -o "$TMP/resp.json" -w "%{http_code}")
CODE=$(python3 -c "import json; print(json.load(open('$TMP/resp.json')).get('code',''))")
if [ "$HTTP" = "409" ] && [ "$CODE" = "ACCOUNT_NOT_ACTIVE" ]; then
  green "  transfers endpoint also gated ✓"
else
  fail "expected 409 ACCOUNT_NOT_ACTIVE; got HTTP=$HTTP code=$CODE"
fi

# ---- restore ----
blue "3. restore account_status → $ORIGINAL_STATUS"
psql_exec "UPDATE brokerage_accounts SET account_status='$ORIGINAL_STATUS' WHERE user_id='$TEST_USER_ID';" > /dev/null
AFTER=$(psql_exec "SELECT account_status FROM brokerage_accounts WHERE user_id='$TEST_USER_ID';" | tr -d ' ')
[ "$AFTER" = "$ORIGINAL_STATUS" ] || fail "failed to restore status (now=$AFTER)"
green "  restored"

# ---- sanity: same GET now succeeds ----
blue "4. GET /v1/funding/transfers after restore → 200"
HTTP=$(curl -sS "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" -o /dev/null -w "%{http_code}")
[ "$HTTP" = "200" ] || fail "expected 200 after restore, got $HTTP"
green "  200 OK"

echo
green "ERRORS SMOKE PASSED"
