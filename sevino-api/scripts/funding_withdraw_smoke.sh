#!/usr/bin/env bash
#
# Verify OUTGOING (withdrawal) transfers work end-to-end.
#
# Unlike deposits, withdrawals require the brokerage account to have settled
# cash — Alpaca sandbox takes 10–30 min to settle an ACH deposit. So this
# script does the wait.
#
# Usage:
#   # Normal (waits for settlement — up to 30 min):
#   bash scripts/funding_withdraw_smoke.sh
#
#   # Assume a deposit has already settled (e.g. you ran --skip-unlink earlier):
#   bash scripts/funding_withdraw_smoke.sh --assume-settled
#
# Prereqs: same as funding_smoke.sh. Seed + source the env first.

set -euo pipefail

ASSUME_SETTLED=0
for arg in "$@"; do
  case "$arg" in
    --assume-settled) ASSUME_SETTLED=1 ;;
    -h|--help) sed -n '1,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

: "${JWT:?Source scripts/.funding_smoke_env first}"
: "${PLAID_CLIENT_ID:?}"
: "${PLAID_SECRET:?}"
: "${ALPACA_ACCOUNT_ID:?}"
: "${BACKEND_URL:=http://localhost:8000}"

AUTH_HEADERS=(-H "Authorization: Bearer $JWT")
if [ -n "${API_KEY:-}" ]; then
  AUTH_HEADERS+=(-H "X-API-Key: $API_KEY")
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m--- %s ---\033[0m\n' "$*"; }
fail()  { red "FAIL: $*"; exit 1; }

# Need to link a bank + deposit first (if --assume-settled is off), wait for
# settlement, then withdraw.

REL_ID=""

if [ "$ASSUME_SETTLED" = "0" ]; then
  blue "1. link bank + deposit (same flow as funding_smoke.sh steps 1–5)"
  # Fresh Plaid item + exchange + reissue
  curl -sS -X POST https://sandbox.plaid.com/sandbox/public_token/create \
    -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"institution_id\":\"ins_109508\",\"initial_products\":[\"auth\"]}" \
    > "$TMP/sandbox.json"
  PT=$(python3 -c "import json; print(json.load(open('$TMP/sandbox.json'))['public_token'])")
  curl -sS -X POST https://sandbox.plaid.com/item/public_token/exchange \
    -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"public_token\":\"$PT\"}" \
    > "$TMP/exchange.json"
  ACCESS=$(python3 -c "import json; print(json.load(open('$TMP/exchange.json'))['access_token'])")
  curl -sS -X POST https://sandbox.plaid.com/accounts/get \
    -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS\"}" \
    > "$TMP/accounts.json"
  ACCOUNT_ID=$(python3 -c "import json; print(json.load(open('$TMP/accounts.json'))['accounts'][0]['account_id'])")
  curl -sS -X POST https://sandbox.plaid.com/item/public_token/create \
    -H "Content-Type: application/json" -H "Plaid-Version: 2019-05-29" \
    -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS\"}" \
    > "$TMP/reissue.json"
  PUBLIC_TOKEN=$(python3 -c "import json; print(json.load(open('$TMP/reissue.json'))['public_token'])")

  curl -sS -X POST "$BACKEND_URL/v1/funding/link-bank" \
    "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
    -d "{\"public_token\":\"$PUBLIC_TOKEN\",\"account_id\":\"$ACCOUNT_ID\",\"institution_name\":\"First Platypus Bank\",\"nickname\":\"Withdraw Checking\"}" \
    > "$TMP/link.json"
  REL_ID=$(python3 -c "import json; print(json.load(open('$TMP/link.json')).get('id',''))")
  [ -n "$REL_ID" ] || fail "link-bank failed: $(cat "$TMP/link.json")"
  green "  linked: $REL_ID"

  blue "2. deposit \$1000 (need enough cash to withdraw from)"
  curl -sS -X POST "$BACKEND_URL/v1/funding/transfers" \
    "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
    -d "{\"relationship_id\":\"$REL_ID\",\"amount\":\"1000.00\",\"direction\":\"INCOMING\"}" \
    > "$TMP/deposit.json"
  DEP_ID=$(python3 -c "import json; print(json.load(open('$TMP/deposit.json')).get('id',''))")
  [ -n "$DEP_ID" ] || fail "deposit failed: $(cat "$TMP/deposit.json")"
  green "  deposit queued: $DEP_ID"

  blue "3. wait for deposit to settle (Alpaca sandbox: 10–30 min)"
  echo "    polling every 60s; ctrl-C to abort"
  DEADLINE=$(($(date +%s) + 2400))  # 40 minutes
  while true; do
    curl -sS "$BACKEND_URL/v1/funding/transfers" \
      "${AUTH_HEADERS[@]}" > "$TMP/poll.json"
    STATUS=$(python3 -c "
import json
ts = json.load(open('$TMP/poll.json'))['transfers']
for t in ts:
  if t['id'] == '$DEP_ID':
    print(t['status'])
    break
else:
  print('MISSING')
")
    echo "    $(date '+%H:%M:%S') status=$STATUS"
    case "$STATUS" in
      COMPLETE) green "  deposit settled"; break ;;
      CANCELED|REJECTED|RETURNED) fail "deposit ended in $STATUS — cannot continue" ;;
    esac
    [ "$(date +%s)" -gt "$DEADLINE" ] && fail "deposit never settled (40 min timeout)"
    sleep 60
  done
else
  blue "1. --assume-settled: looking for an active relationship + completed deposit"
  curl -sS "$BACKEND_URL/v1/funding/ach-relationships" \
    "${AUTH_HEADERS[@]}" > "$TMP/rels.json"
  REL_ID=$(python3 -c "
import json
rels = json.load(open('$TMP/rels.json'))['relationships']
if not rels:
    raise SystemExit('no active relationships — re-run without --assume-settled')
print(rels[0]['id'])
")
  [ -n "$REL_ID" ] || exit 1
  green "  using relationship: $REL_ID"
fi

# ---- withdraw ----
blue "4. POST /v1/funding/transfers (withdraw \$100)"
WDR_STATUS=$(curl -sS -X POST "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
  -d "{\"relationship_id\":\"$REL_ID\",\"amount\":\"100.00\",\"direction\":\"OUTGOING\"}" \
  -o "$TMP/withdraw.json" -w "%{http_code}")
if [ "$WDR_STATUS" != "200" ]; then
  fail "withdrawal: HTTP $WDR_STATUS body=$(cat "$TMP/withdraw.json")"
fi
python3 -c "
import json
d = json.load(open('$TMP/withdraw.json'))
assert d.get('id'), d
assert d['direction'] == 'OUTGOING', d
print(f'  withdrawal id = {d[\"id\"]}, status = {d[\"status\"]}')
"

blue "5. GET /v1/funding/transfers — withdrawal appears in history"
curl -sS "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" > "$TMP/final.json"
python3 -c "
import json
ts = json.load(open('$TMP/final.json'))['transfers']
outgoing = [t for t in ts if t.get('direction') == 'OUTGOING']
assert outgoing, 'no OUTGOING transfer in list'
t = outgoing[0]
bank = t.get('bank') or {}
print(f'  {len(outgoing)} outgoing; bank.nickname = {bank.get(\"nickname\")}')"

echo
green "WITHDRAWAL SMOKE PASSED"
