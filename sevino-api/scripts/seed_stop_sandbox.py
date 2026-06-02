"""Seed the stop-order smoke against an EXISTING funded Alpaca sandbox account.

Paired with `scripts/stop_order_smoke.sh`. Unlike `seed_funding_sandbox.py`
this does NOT create a fresh account — it targets a funded sandbox account you
already have (one that holds at least one whole share of a long equity), so a
SELL stop can be placed immediately without waiting for ACH settlement.

`brokerage_accounts.alpaca_account_id` is unique, so when the account is
already linked locally this authenticates AS its existing owner (via a
Supabase admin magic-link OTP exchange — no password change, no re-linking).
If the account isn't linked locally, a dedicated `stop-smoke@sevino.test` user
is created and linked.

Run:
    uv run python scripts/seed_stop_sandbox.py <alpaca_account_id> [symbol]

If [symbol] is omitted, the first long equity position with >= 1 whole share
is used. The stop trigger is set to half the current price (well below market)
so the resting stop never fires during the smoke and is cleanly cancelable.

Prereqs:
    - Supabase + Redis running locally (`make infra`)
    - Real Alpaca sandbox credentials in `.env`

Writes `scripts/.stop_smoke_env` for the shell script to source.
"""

import asyncio
import sys
import uuid
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

import asyncpg
import httpx

SUPABASE_URL = "http://127.0.0.1:54321"
DB_HOST = "127.0.0.1"
DB_PORT = 54322
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_NAME = "postgres"
SERVICE_ROLE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)

FALLBACK_EMAIL = "stop-smoke@sevino.test"

ALPACA_AUTH_URL = "https://authx.sandbox.alpaca.markets/v1/oauth2/token"
ALPACA_BASE_URL = "https://broker-api.sandbox.alpaca.markets"


def _read_env_file() -> dict[str, str]:
    env_path = Path(__file__).parent.parent / ".env"
    data: dict[str, str] = {}
    if not env_path.exists():
        return data
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _admin_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "apikey": SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }


def _create_confirmed_user(email: str) -> str:
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=_admin_headers(),
        json={"email": email, "email_confirm": True},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _mint_jwt(email: str) -> str:
    """Mint an access token for a confirmed user via the admin magic-link OTP
    exchange — no password required, no user mutation."""
    gen = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/generate_link",
        headers=_admin_headers(),
        json={"type": "magiclink", "email": email},
    )
    gen.raise_for_status()
    otp = gen.json()["email_otp"]
    verify = httpx.post(
        f"{SUPABASE_URL}/auth/v1/verify",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"type": "magiclink", "email": email, "token": otp},
    )
    verify.raise_for_status()
    return verify.json()["access_token"]


def _alpaca_token(api_key: str, secret: str) -> str:
    resp = httpx.post(
        ALPACA_AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _pick_position(
    token: str, account_id: str, wanted_symbol: str | None
) -> tuple[str, Decimal, Decimal]:
    """Return (symbol, held_qty, current_price) for a long equity holding."""
    resp = httpx.get(
        f"{ALPACA_BASE_URL}/v1/trading/accounts/{account_id}/positions",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"list positions failed: {resp.status_code} {resp.text}"
        )
    positions = resp.json()
    if not positions:
        raise RuntimeError(
            f"account {account_id} holds no positions — buy a whole share "
            "first, or pass an account that already holds one."
        )

    def _long_whole(p: dict) -> bool:
        try:
            qty = Decimal(str(p.get("qty", "0")))
        except Exception:
            return False
        return p.get("side") == "long" and qty.to_integral_value(ROUND_FLOOR) >= 1

    candidates = [p for p in positions if _long_whole(p)]
    if wanted_symbol:
        candidates = [
            p
            for p in candidates
            if p.get("symbol", "").upper() == wanted_symbol.upper()
        ]
    if not candidates:
        held = ", ".join(
            f"{p.get('symbol')}({p.get('qty')})" for p in positions
        )
        raise RuntimeError(
            "no long position with >= 1 whole share"
            + (f" matching {wanted_symbol}" if wanted_symbol else "")
            + f". Holdings: {held}"
        )
    p = candidates[0]
    symbol = p["symbol"].upper()
    held_qty = Decimal(str(p["qty"]))
    current_price = Decimal(str(p.get("current_price") or p["avg_entry_price"]))
    return symbol, held_qty, current_price


async def _find_account_owner(account_id: str) -> tuple[str, str] | None:
    """Return (user_id, email) of the existing local owner of this Alpaca
    account, or None if it isn't linked locally."""
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        row = await conn.fetchrow(
            """
            SELECT up.id, up.email
            FROM brokerage_accounts ba
            JOIN user_profiles up ON up.id = ba.user_id
            WHERE ba.alpaca_account_id = $1
            """,
            account_id,
        )
        return (str(row["id"]), row["email"]) if row else None
    finally:
        await conn.close()


async def _ensure_active(user_id: str) -> None:
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        await conn.execute(
            """
            UPDATE brokerage_accounts
            SET account_status = 'ACTIVE',
                activated_at = COALESCE(activated_at, now()),
                updated_at = now()
            WHERE user_id = $1
            """,
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()


async def _link_new_user(user_id: str, email: str, account_id: str) -> None:
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        user_uuid = uuid.UUID(user_id)
        await conn.execute(
            """
            INSERT INTO user_profiles (id, email, created_at, updated_at)
            VALUES ($1, $2, now(), now())
            ON CONFLICT (id) DO NOTHING
            """,
            user_uuid,
            email,
        )
        await conn.execute(
            """
            INSERT INTO brokerage_accounts (
                id, user_id, alpaca_account_id, account_status,
                kyc_submitted_at, activated_at, created_at, updated_at
            ) VALUES (
                $1, $2, $3, 'ACTIVE', now(), now(), now(), now()
            )
            ON CONFLICT (user_id) DO UPDATE SET
                alpaca_account_id = EXCLUDED.alpaca_account_id,
                account_status = 'ACTIVE',
                updated_at = now()
            """,
            uuid.uuid4(),
            user_uuid,
            account_id,
        )
    finally:
        await conn.close()


async def _upsert_asset(symbol: str) -> None:
    conn = await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )
    try:
        await conn.execute(
            """
            INSERT INTO assets (symbol, name, tradeable, fractionable, synced_at)
            VALUES ($1, $1, TRUE, TRUE, now())
            ON CONFLICT (symbol) DO UPDATE SET tradeable = TRUE
            """,
            symbol,
        )
    finally:
        await conn.close()


async def main(alpaca_account_id: str, wanted_symbol: str | None) -> int:
    env = _read_env_file()
    alpaca_key = env.get("ALPACA_API_KEY", "")
    alpaca_secret = env.get("ALPACA_SECRET_KEY", "")
    if not alpaca_key or alpaca_key.startswith("your-"):
        print("ERROR: ALPACA_API_KEY missing or placeholder in .env", file=sys.stderr)
        return 1

    owner = await _find_account_owner(alpaca_account_id)
    if owner is not None:
        user_id, email = owner
        print(f"→ account already linked locally → authenticating as {email}")
        await _ensure_active(user_id)
    else:
        print(f"→ account not linked locally → creating {FALLBACK_EMAIL}")
        email = FALLBACK_EMAIL
        user_id = _create_confirmed_user(email)
        await _link_new_user(user_id, email, alpaca_account_id)
    print(f"  user_id = {user_id}")

    print(f"→ inspecting positions on {alpaca_account_id}")
    token = _alpaca_token(alpaca_key, alpaca_secret)
    symbol, held_qty, current_price = _pick_position(
        token, alpaca_account_id, wanted_symbol
    )
    # Alpaca rejects non-penny ticks and stops on sub-$1 stocks.
    stop_below = (current_price / 2).quantize(Decimal("0.01"))
    stop_above = (current_price * 2).quantize(Decimal("0.01"))
    qty = "1"
    print(
        f"  holding {held_qty} {symbol} @ ${current_price} "
        f"→ sell stop {qty} @ ${stop_below} (below), buy stop @ ${stop_above} (above)"
    )

    print("→ ensuring the asset row exists (tradeable)")
    await _upsert_asset(symbol)

    print("→ minting a JWT (admin magic-link OTP, no password change)")
    jwt = _mint_jwt(email)

    out_path = Path(__file__).parent / ".stop_smoke_env"
    out_path.write_text(
        "# Source this before running stop_order_smoke.sh\n"
        f"export TEST_USER_ID='{user_id}'\n"
        f"export TEST_EMAIL='{email}'\n"
        f"export ALPACA_ACCOUNT_ID='{alpaca_account_id}'\n"
        f"export JWT='{jwt}'\n"
        f"export API_KEY='{env.get('API_KEY', '')}'\n"
        f"export BACKEND_URL='http://localhost:8000'\n"
        f"export SYMBOL='{symbol}'\n"
        f"export QTY='{qty}'\n"
        f"export CURRENT_PRICE='{current_price}'\n"
        f"export STOP_PRICE='{stop_below}'\n"
        f"export STOP_BELOW='{stop_below}'\n"
        f"export STOP_ABOVE='{stop_above}'\n"
    )
    out_path.chmod(0o600)
    print(f"✓ wrote {out_path}")
    print()
    print("Next:")
    print("  1. make server   (run in another terminal)")
    print("  2. source scripts/.stop_smoke_env")
    print("  3. bash scripts/stop_order_smoke.sh")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(2)
    arg_symbol = sys.argv[2] if len(sys.argv) == 3 else None
    sys.exit(asyncio.run(main(sys.argv[1], arg_symbol)))
