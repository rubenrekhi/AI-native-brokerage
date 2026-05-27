#!/usr/bin/env bash
#
# Smoke-tests the SEV-225 re-auth pipeline end-to-end:
#   link a fresh sandbox item → sandbox/item/reset_login → Plaid webhook →
#   POST /v1/plaid/webhooks → DB flip → GET /v1/funding/ach-relationships
#   shows requires_reauth=true.
#
# Self-contained: links its own item per run (no dependency on prior
# funding_smoke.sh state).
#
# Prerequisites:
#   1. PLAID_WEBHOOK_URL set on the backend (Railway staging shared vars)
#   2. uv run python scripts/seed_funding_sandbox.py  (one-time, mints JWT)
#   3. source scripts/.funding_smoke_env
#
# Usage:
#   bash scripts/funding_reauth_smoke.sh           # full flow
#   bash scripts/funding_reauth_smoke.sh --help

set -euo pipefail

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown arg: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

: "${JWT:?Source scripts/.funding_smoke_env first}"
: "${PLAID_CLIENT_ID:?}"
: "${PLAID_SECRET:?}"
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

# ---- 1. mint + exchange + reissue a fresh Plaid sandbox item ----
blue "1. Plaid sandbox: mint + exchange + reissue public_token"
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

# ---- 2. POST /v1/funding/link-bank ----
blue "2. POST /v1/funding/link-bank"
curl -sS -X POST "$BACKEND_URL/v1/funding/link-bank" \
  "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
  -d "{\"public_token\":\"$PUBLIC_TOKEN\",\"account_id\":\"$ACCOUNT_ID\",\"institution_name\":\"First Platypus Bank\",\"nickname\":\"Reauth Smoke\"}" \
  > "$TMP/link_bank.json"
REL_ID=$(python3 -c "import json; print(json.load(open('$TMP/link_bank.json')).get('id', ''))")
if [ -z "$REL_ID" ]; then fail "link-bank: $(cat "$TMP/link_bank.json")"; fi
green "  local id = $REL_ID"

# ---- 3. force ITEM_LOGIN_REQUIRED ----
blue "3. POST https://sandbox.plaid.com/sandbox/item/reset_login"
curl -sS -X POST https://sandbox.plaid.com/sandbox/item/reset_login \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS\"}" \
  > "$TMP/reset.json"
python3 -c "
import json
assert json.load(open('$TMP/reset.json')).get('reset_login') is True, 'unexpected response'
print('  reset_login = True')
"

# ---- 4. poll the API until requires_reauth flips ----
blue "4. poll GET /v1/funding/ach-relationships (30s max, 3s interval)"
fetch_requires_reauth() {
  curl -sS "$BACKEND_URL/v1/funding/ach-relationships" "${AUTH_HEADERS[@]}" \
    > "$TMP/rels.json"
  python3 -c "
import json, sys
rels = json.load(open('$TMP/rels.json')).get('relationships', [])
match = next((r for r in rels if r['id'] == '$REL_ID'), None)
if not match:
    print('missing', file=sys.stderr); sys.exit(2)
print('true' if match.get('requires_reauth') else 'false')
"
}

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  STATE=$(fetch_requires_reauth)
  if [ "$STATE" = "true" ]; then
    green "  ok after ${attempt}x3s — webhook delivered, requires_reauth=true"
    exit 0
  fi
  sleep 3
done

fail "requires_reauth still false after 30s. Check (a) PLAID_WEBHOOK_URL is set on the backend, (b) the backend was redeployed after SEV-593, (c) Plaid sandbox can reach the webhook URL"
