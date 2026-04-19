#!/usr/bin/env bash
#
# Funding stack end-to-end smoke against real Plaid + Alpaca sandbox envs.
# Exercises the flow an iOS client would drive:
#   link-token → link-bank → list → deposit → list transfers → unlink → re-list
#
# Prerequisites:
#   1. `make server` running in another terminal
#   2. `uv run python scripts/seed_funding_sandbox.py`
#   3. `source scripts/.funding_smoke_env`
#
# Usage:
#   bash scripts/funding_smoke.sh               # full flow, including unlink
#   bash scripts/funding_smoke.sh --skip-unlink # leave the bank + transfer live
#                                                (use this to watch Alpaca
#                                                settle the deposit over 10–30min
#                                                in the sandbox dashboard)
#   bash scripts/funding_smoke.sh --help
#
# Sandbox gotcha: Plaid public_tokens are one-shot, and account_ids differ
# across items. We use the legacy `/item/public_token/create` endpoint
# (Plaid-Version 2019-05-29) to reissue a fresh public_token for the *same*
# item, so the account_id we grabbed stays valid when our backend exchanges
# the reissued token.

set -euo pipefail

# ---- flag parsing ----
SKIP_UNLINK=0
for arg in "$@"; do
  case "$arg" in
    --skip-unlink) SKIP_UNLINK=1 ;;
    -h|--help)
      sed -n '1,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown arg: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

# ---- required env ----
: "${JWT:?Source scripts/.funding_smoke_env first (run seed_funding_sandbox.py)}"
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

# ---- 1. mint sandbox public_token, exchange, get accounts, reissue ----
blue "1. Plaid sandbox: mint + exchange + list accounts + reissue public_token"
curl -sS -X POST https://sandbox.plaid.com/sandbox/public_token/create \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"institution_id\":\"ins_109508\",\"initial_products\":[\"auth\"]}" \
  > "$TMP/sandbox.json"
PT_A=$(python3 -c "import json; print(json.load(open('$TMP/sandbox.json'))['public_token'])")

curl -sS -X POST https://sandbox.plaid.com/item/public_token/exchange \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"public_token\":\"$PT_A\"}" \
  > "$TMP/exchange.json"
ACCESS=$(python3 -c "import json; print(json.load(open('$TMP/exchange.json'))['access_token'])")

curl -sS -X POST https://sandbox.plaid.com/accounts/get \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS\"}" \
  > "$TMP/accounts.json"
ACCOUNT_ID=$(python3 -c "import json; print(json.load(open('$TMP/accounts.json'))['accounts'][0]['account_id'])")

curl -sS -X POST https://sandbox.plaid.com/item/public_token/create \
  -H "Content-Type: application/json" \
  -H "Plaid-Version: 2019-05-29" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS\"}" \
  > "$TMP/reissue.json"
PUBLIC_TOKEN=$(python3 -c "import json; print(json.load(open('$TMP/reissue.json'))['public_token'])")
green "  Plaid account_id = $ACCOUNT_ID"

# ---- 2. link-token ----
blue "2. POST /v1/funding/link-token"
curl -sS -X POST "$BACKEND_URL/v1/funding/link-token" \
  "${AUTH_HEADERS[@]}" > "$TMP/link_token.json"
LINK_TOKEN=$(python3 -c "import json; print(json.load(open('$TMP/link_token.json')).get('link_token',''))")
case "$LINK_TOKEN" in
  link-sandbox-*) green "  ok ($LINK_TOKEN)" ;;
  *) fail "link-token bad: $(cat "$TMP/link_token.json")" ;;
esac

# ---- 3. link-bank ----
blue "3. POST /v1/funding/link-bank"
curl -sS -X POST "$BACKEND_URL/v1/funding/link-bank" \
  "${AUTH_HEADERS[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"public_token\":\"$PUBLIC_TOKEN\",\"account_id\":\"$ACCOUNT_ID\",\"institution_name\":\"First Platypus Bank\",\"account_mask\":\"0000\",\"nickname\":\"Smoke Checking\"}" \
  > "$TMP/link_bank.json"
REL_ID=$(python3 -c "import json,sys; d=json.load(open('$TMP/link_bank.json')); print(d.get('id',''))")
if [ -z "$REL_ID" ]; then fail "link-bank: $(cat "$TMP/link_bank.json")"; fi
python3 -c "
import json
d = json.load(open('$TMP/link_bank.json'))
assert d.get('alpaca_relationship_id'), 'missing alpaca_relationship_id'
print(f'  local id               = {d[\"id\"]}')
print(f'  alpaca_relationship_id = {d[\"alpaca_relationship_id\"]}')
print(f'  status                 = {d[\"status\"]}')
print(f'  nickname               = {d[\"nickname\"]}')
"

# ---- 3b. verify access token is stored encrypted in the DB ----
blue "3b. verify plaid_access_token is Fernet ciphertext at rest"
PREFIX=$(PGPASSWORD=postgres psql -tAX -h localhost -p 54322 -U postgres -d postgres \
  -c "SELECT LEFT(plaid_access_token, 6) FROM plaid_items WHERE plaid_item_id NOT IN (SELECT plaid_item_id FROM plaid_items WHERE status='inactive') ORDER BY created_at DESC LIMIT 1;")
PREFIX=$(echo "$PREFIX" | tr -d ' \n')
case "$PREFIX" in
  gAAAAA*) green "  ciphertext prefix = $PREFIX (Fernet)" ;;
  access-*) fail "plaintext Plaid token in DB (prefix=$PREFIX)" ;;
  "")      fail "no plaid_items row found" ;;
  *)       fail "unexpected ciphertext prefix in DB: $PREFIX" ;;
esac

# ---- 3c. re-link the same underlying bank → expect 409 BANK_ALREADY_LINKED ----
blue "3c. POST /v1/funding/link-bank again (fresh Plaid item, same bank) → expect 409"
# Second fresh Plaid item — different item_id so we skip the fast-path,
# but same underlying bank details, so Alpaca should 409.
curl -sS -X POST https://sandbox.plaid.com/sandbox/public_token/create \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"institution_id\":\"ins_109508\",\"initial_products\":[\"auth\"]}" \
  > "$TMP/sandbox2.json"
PT2_A=$(python3 -c "import json; print(json.load(open('$TMP/sandbox2.json'))['public_token'])")
curl -sS -X POST https://sandbox.plaid.com/item/public_token/exchange \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"public_token\":\"$PT2_A\"}" \
  > "$TMP/exchange2.json"
ACCESS2=$(python3 -c "import json; print(json.load(open('$TMP/exchange2.json'))['access_token'])")
curl -sS -X POST https://sandbox.plaid.com/accounts/get \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS2\"}" \
  > "$TMP/accounts2.json"
ACCOUNT_ID2=$(python3 -c "import json; print(json.load(open('$TMP/accounts2.json'))['accounts'][0]['account_id'])")
curl -sS -X POST https://sandbox.plaid.com/item/public_token/create \
  -H "Content-Type: application/json" -H "Plaid-Version: 2019-05-29" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"access_token\":\"$ACCESS2\"}" \
  > "$TMP/reissue2.json"
PUBLIC_TOKEN2=$(python3 -c "import json; print(json.load(open('$TMP/reissue2.json'))['public_token'])")

DUP_STATUS=$(curl -sS -X POST "$BACKEND_URL/v1/funding/link-bank" \
  "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
  -d "{\"public_token\":\"$PUBLIC_TOKEN2\",\"account_id\":\"$ACCOUNT_ID2\",\"institution_name\":\"First Platypus Bank\",\"nickname\":\"Duplicate\"}" \
  -o "$TMP/dup.json" -w "%{http_code}")
DUP_CODE=$(python3 -c "import json; print(json.load(open('$TMP/dup.json')).get('code',''))")
if [ "$DUP_STATUS" = "409" ] && [ "$DUP_CODE" = "BANK_ALREADY_LINKED" ]; then
  green "  409 BANK_ALREADY_LINKED ✓"
else
  fail "expected 409 BANK_ALREADY_LINKED, got HTTP $DUP_STATUS code=$DUP_CODE body=$(cat "$TMP/dup.json")"
fi

# ---- 4. list relationships ----
blue "4. GET /v1/funding/ach-relationships"
curl -sS "$BACKEND_URL/v1/funding/ach-relationships" \
  "${AUTH_HEADERS[@]}" > "$TMP/list.json"
python3 -c "
import json
rels = json.load(open('$TMP/list.json'))
assert isinstance(rels, list) and any(r['id'] == '$REL_ID' for r in rels), f'rel missing from list: {rels}'
print(f'  {len(rels)} active relationship(s)')
"

# ---- 5. deposit ----
blue "5. POST /v1/funding/transfers (deposit \$500)"
curl -sS -X POST "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"relationship_id\":\"$REL_ID\",\"amount\":\"500.00\",\"direction\":\"INCOMING\"}" \
  > "$TMP/transfer.json"
TRANSFER_ID=$(python3 -c "import json; print(json.load(open('$TMP/transfer.json')).get('id',''))")
python3 -c "
import json
d = json.load(open('$TMP/transfer.json'))
assert d.get('id'), f'no transfer id: {d}'
print(f'  transfer id = {d[\"id\"]}, status = {d[\"status\"]}')
"

# ---- 6. list transfers (active rel) ----
blue "6. GET /v1/funding/transfers"
curl -sS "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" > "$TMP/transfers.json"
python3 -c "
import json
d = json.load(open('$TMP/transfers.json'))
ts = d.get('transfers', [])
assert ts, f'expected at least one transfer: {d}'
t = ts[0]
bank = t.get('bank') or {}
assert bank.get('nickname') == 'Smoke Checking', f'nickname merge failed: {bank}'
print(f'  {len(ts)} transfer(s); first bank.nickname = {bank[\"nickname\"]}')
"

if [ "$SKIP_UNLINK" = "1" ]; then
  echo
  green "✓ link + deposit verified — skipping unlink so you can watch settlement"
  echo
  echo "  Transfer id:               $TRANSFER_ID"
  echo "  Relationship (backend pk): $REL_ID"
  echo
  echo "  To watch settlement:"
  echo "    curl -sS '$BACKEND_URL/v1/funding/transfers' \\"
  echo "      -H \"Authorization: Bearer \$JWT\" | python3 -m json.tool"
  echo
  echo "  Status will advance QUEUED → PENDING → COMPLETE over 10–30 min."
  echo "  After it completes, re-run without --skip-unlink to verify the"
  echo "  post-unlink historical-transfer display."
  exit 0
fi

# ---- 7. unlink ----
blue "7. DELETE /v1/funding/ach-relationships/$REL_ID"
STATUS=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE \
  "$BACKEND_URL/v1/funding/ach-relationships/$REL_ID" "${AUTH_HEADERS[@]}")
[ "$STATUS" = "204" ] || fail "expected 204, got $STATUS"
green "  204 OK"

# ---- 8. re-list relationships ----
blue "8. GET /v1/funding/ach-relationships (after unlink)"
curl -sS "$BACKEND_URL/v1/funding/ach-relationships" \
  "${AUTH_HEADERS[@]}" > "$TMP/list2.json"
python3 -c "
import json
rels = json.load(open('$TMP/list2.json'))
assert not any(r['id'] == '$REL_ID' for r in rels), 'canceled rel still listed'
print(f'  {len(rels)} active relationship(s) remaining')
"

# ---- 9. transfers still show historical one with bank metadata ----
blue "9. GET /v1/funding/transfers (historical + canceled rel)"
curl -sS "$BACKEND_URL/v1/funding/transfers" \
  "${AUTH_HEADERS[@]}" > "$TMP/transfers2.json"
python3 -c "
import json
d = json.load(open('$TMP/transfers2.json'))
ts = d.get('transfers', [])
assert ts, 'historical transfers vanished'
t = ts[0]
bank = t.get('bank') or {}
assert bank.get('nickname') == 'Smoke Checking', f'nickname lost after unlink: {bank}'
print(f'  historical transfer keeps bank.nickname = {bank[\"nickname\"]}')
"

# ---- 10. no plaintext Plaid access tokens in any backend response ----
blue "10. scan backend responses for plaintext Plaid access tokens"
for f in link_token.json link_bank.json list.json transfer.json transfers.json list2.json transfers2.json; do
  if grep -E "access-sandbox-|access-production-" "$TMP/$f" > /dev/null; then
    fail "plaintext access token leaked in $f"
  fi
done
green "  clean — ciphertext stays in the database, never on the wire"

echo
green "ALL FUNDING SMOKE CHECKS PASSED"
