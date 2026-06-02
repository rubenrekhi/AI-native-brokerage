#!/usr/bin/env bash
#
# Stop-order coverage smoke against the real Alpaca sandbox. Exercises what
# the mocked unit/integration tests cannot:
#   1. SELL stop (below market) — place → read → cancel. The protective case.
#   2. BUY stop (above market)  — place → cancel. The other direction we ship.
#   3. WRONG-SIDE sell stop (above market) — informational: does Alpaca reject
#      (→ our 422 ALPACA_ERROR) or accept + trigger? Validates "defer to Alpaca".
#   4. GET /v1/brokerage/orders — a placed stop surfaces with its stop_price
#      in the list projection iOS reads.
#
# Confirms: sandbox accepts type=stop + stop_price + gtc, echoes stop_price,
# what status a resting stop reports, and that resting stops are cancelable.
#
# Prerequisites:
#   1. `make server` running in another terminal
#   2. `uv run python scripts/seed_stop_sandbox.py <alpaca_account_id> [symbol]`
#   3. `source scripts/.stop_smoke_env`
#
# Usage:
#   bash scripts/stop_order_smoke.sh             # all cases, each canceled
#   bash scripts/stop_order_smoke.sh --help

set -euo pipefail

for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '1,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg (try --help)" >&2; exit 2 ;;
  esac
done

: "${JWT:?Source scripts/.stop_smoke_env first (run seed_stop_sandbox.py)}"
: "${SYMBOL:?}"
: "${QTY:?}"
: "${STOP_BELOW:?}"
: "${STOP_ABOVE:?}"
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

# place_stop <side> <stop_price> <out.json> -> echoes the HTTP status code
place_stop() {
  curl -sS -X POST "$BACKEND_URL/v1/trading/orders" \
    "${AUTH_HEADERS[@]}" -H "Content-Type: application/json" \
    -d "{\"symbol\":\"$SYMBOL\",\"side\":\"$1\",\"type\":\"stop\",\"qty\":\"$QTY\",\"stop_price\":\"$2\"}" \
    -o "$3" -w "%{http_code}"
}

cancel_stop() {  # cancel_stop <order_id>
  curl -sS -o /dev/null -w "%{http_code}" -X DELETE \
    "$BACKEND_URL/v1/trading/orders/$1" "${AUTH_HEADERS[@]}" || true
}

# ---- 1. SELL stop below market: place → read → cancel ----
blue "1. SELL stop below market (sell $QTY $SYMBOL @ \$$STOP_BELOW)"
HTTP=$(place_stop sell "$STOP_BELOW" "$TMP/sell.json")
[ "$HTTP" = "201" ] || fail "expected 201, got $HTTP — $(cat "$TMP/sell.json")"
SELL_ID=$(python3 -c "import json; print(json.load(open('$TMP/sell.json'))['id'])")
python3 - "$TMP/sell.json" "$STOP_BELOW" <<'PY'
import json, sys
from decimal import Decimal
d = json.load(open(sys.argv[1]))
assert d["type"] == "stop" and d["time_in_force"] == "gtc", d
assert Decimal(d["stop_price"]) == Decimal(sys.argv[2]), d.get("stop_price")
assert d.get("limit_price") is None, d.get("limit_price")
print(f'  201 | stop_price echo={d["stop_price"]} tif={d["time_in_force"]} status={d["status"]}')
PY
curl -sS "$BACKEND_URL/v1/trading/orders/$SELL_ID" "${AUTH_HEADERS[@]}" > "$TMP/sell_get.json"
python3 - "$TMP/sell_get.json" "$STOP_BELOW" <<'PY'
import json, sys
from decimal import Decimal
d = json.load(open(sys.argv[1]))
assert d["type"] == "stop" and Decimal(d["stop_price"]) == Decimal(sys.argv[2]), d
print(f'  GET persisted stop_price={d["stop_price"]} status={d["status"]}')
PY
[ "$(cancel_stop "$SELL_ID")" = "200" ] || fail "sell-stop cancel failed"
green "  sell stop: placed, echoed, persisted, canceled"

# ---- 2. BUY stop above market: place → cancel ----
blue "2. BUY stop above market (buy $QTY $SYMBOL @ \$$STOP_ABOVE)"
HTTP=$(place_stop buy "$STOP_ABOVE" "$TMP/buy.json")
[ "$HTTP" = "201" ] || fail "expected 201, got $HTTP — $(cat "$TMP/buy.json")"
BUY_ID=$(python3 -c "import json; print(json.load(open('$TMP/buy.json'))['id'])")
python3 - "$TMP/buy.json" "$STOP_ABOVE" <<'PY'
import json, sys
from decimal import Decimal
d = json.load(open(sys.argv[1]))
assert d["type"] == "stop" and d["side"] == "buy" and d["time_in_force"] == "gtc", d
assert Decimal(d["stop_price"]) == Decimal(sys.argv[2]), d.get("stop_price")
print(f'  201 | side={d["side"]} stop_price echo={d["stop_price"]} status={d["status"]}')
PY
[ "$(cancel_stop "$BUY_ID")" = "200" ] || fail "buy-stop cancel failed"
green "  buy stop: placed, echoed, canceled"

# ---- 3. WRONG-SIDE sell stop above market (informational) ----
blue "3. WRONG-SIDE sell stop above market (sell @ \$$STOP_ABOVE > market) — observe Alpaca"
HTTP=$(place_stop sell "$STOP_ABOVE" "$TMP/wrong.json")
case "$HTTP" in
  201)
    WRONG_ID=$(python3 -c "import json; print(json.load(open('$TMP/wrong.json'))['id'])")
    STATUS=$(python3 -c "import json; print(json.load(open('$TMP/wrong.json'))['status'])")
    red "  OBSERVED: Alpaca ACCEPTED a wrong-side sell stop (201, status=$STATUS)."
    red "           It would trigger an immediate market SELL at next open."
    red "           => 'defer to Alpaca' does NOT guard this; consider a client/UX warning."
    CODE=$(cancel_stop "$WRONG_ID")
    green "  canceled the wrong-side order (HTTP $CODE) — no open exposure left"
    ;;
  4??)
    CODE=$(python3 -c "import json; print(json.load(open('$TMP/wrong.json')).get('code',''))" 2>/dev/null || echo "")
    green "  OBSERVED: Alpaca REJECTED it (HTTP $HTTP, code=$CODE) → surfaced via our error mapping."
    green "           => 'defer to Alpaca' is safe; no extra guard needed."
    ;;
  *)
    fail "unexpected HTTP $HTTP on wrong-side stop — $(cat "$TMP/wrong.json")"
    ;;
esac

# ---- 4. list projection surfaces stop_price ----
blue "4. GET /v1/brokerage/orders — a stop surfaces with stop_price"
# Place one resting sell stop, list, assert it appears with stop_price, cancel.
HTTP=$(place_stop sell "$STOP_BELOW" "$TMP/list_seed.json")
[ "$HTTP" = "201" ] || fail "could not seed list order, HTTP $HTTP"
LIST_ID=$(python3 -c "import json; print(json.load(open('$TMP/list_seed.json'))['id'])")
ALP_ID=$(python3 -c "import json; print(json.load(open('$TMP/list_seed.json'))['alpaca_order_id'])")
curl -sS "$BACKEND_URL/v1/brokerage/orders?status=open" "${AUTH_HEADERS[@]}" > "$TMP/orders.json" \
  || curl -sS "$BACKEND_URL/v1/brokerage/orders" "${AUTH_HEADERS[@]}" > "$TMP/orders.json"
python3 - "$TMP/orders.json" "$ALP_ID" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
orders = d.get("orders", d if isinstance(d, list) else [])
stops = [o for o in orders if o.get("type") == "stop" or o.get("order_type") == "stop"]
assert stops, f"no stop order in list projection: keys={list(d) if isinstance(d, dict) else type(d)}"
s = stops[0]
assert s.get("stop_price") is not None, f"list projection dropped stop_price: {s}"
print(f'  {len(stops)} stop order(s) listed; first stop_price={s["stop_price"]} status={s.get("status")}')
PY
[ "$(cancel_stop "$LIST_ID")" = "200" ] || fail "list-seed cancel failed"
green "  GET /v1/brokerage/orders surfaces stop_price (the path iOS reads)"

echo
green "ALL STOP-ORDER SANDBOX COVERAGE CHECKS PASSED"
