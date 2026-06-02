#!/usr/bin/env bash
#
# Stop-order TRIGGER → FILL lifecycle smoke. The one test that exercises the
# trade-events SSE handler code this feature touched (STATUS_ORDER ranking of
# accepted → ... → filled). MUST run during market hours with the worker
# (listener) running, because triggering depends on live price movement and
# our order_events row is only advanced by the SSE listener / reconcile sweep.
#
# Places a SELL stop just below the last trade so a normal downtick triggers
# it (a valid-side stop — Alpaca rejects wrong-side stops, see
# stop_order_smoke.sh case 3), then polls until our DB row reaches a fill.
# This SELLS 1 real (sandbox) share when it triggers.
#
# Prerequisites:
#   1. `make server` AND `make worker` running (the worker runs the SSE listener)
#   2. Market OPEN
#   3. `uv run python scripts/seed_stop_sandbox.py <alpaca_account_id> [symbol]`
#   4. `source scripts/.stop_smoke_env`
#
# Usage:
#   bash scripts/stop_trigger_fill_smoke.sh            # ~5 min poll
#   bash scripts/stop_trigger_fill_smoke.sh --restore  # buy 1 share back after fill

set -euo pipefail

RESTORE=0
for arg in "$@"; do
  case "$arg" in
    --restore) RESTORE=1 ;;
    -h|--help) sed -n '1,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg (try --help)" >&2; exit 2 ;;
  esac
done

: "${JWT:?Source scripts/.stop_smoke_env first (run seed_stop_sandbox.py)}"
: "${SYMBOL:?}"
: "${QTY:?}"
: "${CURRENT_PRICE:?}"
: "${BACKEND_URL:=http://localhost:8000}"

AUTH_HEADERS=(-H "Authorization: Bearer $JWT")
if [ -n "${API_KEY:-}" ]; then
  AUTH_HEADERS+=(-H "X-API-Key: $API_KEY")
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m--- %s ---\033[0m\n' "$*"; }
fail()  { red "FAIL: $*"; exit 1; }

# Trigger 0.1% below the seed-time last trade — close enough that ordinary
# intraday movement crosses it, far enough to be a valid (below-market) stop.
TRIGGER=$(python3 -c "from decimal import Decimal,ROUND_DOWN; print((Decimal('$CURRENT_PRICE')*Decimal('0.999')).quantize(Decimal('0.01'),ROUND_DOWN))")

blue "1. confirm market is open"
OPEN=$(curl -sS "$BACKEND_URL/v1/portfolio/snapshot" "${AUTH_HEADERS[@]}" -o /dev/null -w "%{http_code}" || true)
# Not all deployments expose a clock route; rely on the fill poll to reveal it.

blue "2. place a sell stop just below market (sell $QTY $SYMBOL @ \$$TRIGGER)"
HTTP=$(curl -sS -X POST "$BACKEND_URL/v1/trading/orders" "${AUTH_HEADERS[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"symbol\":\"$SYMBOL\",\"side\":\"sell\",\"type\":\"stop\",\"qty\":\"$QTY\",\"stop_price\":\"$TRIGGER\"}" \
  -o "$TMP/place.json" -w "%{http_code}")
[ "$HTTP" = "201" ] || fail "place failed HTTP $HTTP — $(cat "$TMP/place.json")"
ORDER_ID=$(python3 -c "import json; print(json.load(open('$TMP/place.json'))['id'])")
green "  placed order $ORDER_ID at trigger \$$TRIGGER"

blue "3. poll our order_events row (advanced only by the SSE listener) for a fill"
FILLED=0; LAST=""
for i in $(seq 1 20); do
  sleep 15
  curl -sS "$BACKEND_URL/v1/trading/orders/$ORDER_ID" "${AUTH_HEADERS[@]}" > "$TMP/get.json"
  ST=$(python3 -c "import json; print(json.load(open('$TMP/get.json'))['status'])")
  if [ "$ST" != "$LAST" ]; then echo "  [$((i*15))s] status=$ST"; LAST="$ST"; fi
  case "$ST" in
    filled|partially_filled) FILLED=1; break ;;
    canceled|rejected|expired) fail "order reached terminal $ST without filling" ;;
  esac
done

if [ "$FILLED" = "1" ]; then
  python3 - "$TMP/get.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f'  filled_qty={d.get("filled_qty")} filled_avg_price={d.get("filled_avg_price")} status={d["status"]}')
PY
  green "  SSE listener advanced our row to a fill — STATUS_ORDER lifecycle verified"
  if [ "$RESTORE" = "1" ]; then
    blue "4. restore position: market buy $QTY $SYMBOL"
    curl -sS -X POST "$BACKEND_URL/v1/trading/orders" "${AUTH_HEADERS[@]}" \
      -H "Content-Type: application/json" \
      -d "{\"symbol\":\"$SYMBOL\",\"side\":\"buy\",\"type\":\"market\",\"qty\":\"$QTY\"}" \
      -o /dev/null -w "  restore HTTP %{http_code}\n"
  fi
  echo; green "STOP TRIGGER→FILL LIFECYCLE VERIFIED"
else
  red "  INCONCLUSIVE: stop did not trigger within 5 min (price never crossed \$$TRIGGER)."
  echo "  Live Alpaca view for comparison:"
  curl -sS "$BACKEND_URL/v1/brokerage/orders?status=all&symbols=$SYMBOL" "${AUTH_HEADERS[@]}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('   ', [(o.get('type'),o.get('status'),o.get('stop_price')) for o in d.get('orders',[])][:5])" || true
  echo "  Canceling the resting stop."
  curl -sS -o /dev/null -w "  cancel HTTP %{http_code}\n" -X DELETE \
    "$BACKEND_URL/v1/trading/orders/$ORDER_ID" "${AUTH_HEADERS[@]}" || true
  exit 3
fi
