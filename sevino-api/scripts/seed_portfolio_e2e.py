"""Seed a phone-OTP test user linked to an existing Alpaca sandbox account.

For the holdings modal sim walk-through. Unlike `seed_funding_sandbox.py`
this does NOT create a fresh Alpaca account — it points the local
`brokerage_accounts` row at an existing one (presumably one that already
has positions placed by another developer).

Run:
    uv run python scripts/seed_portfolio_e2e.py <alpaca_account_id>

After running, on the iOS simulator:
    phone:  15551234567
    OTP:    123456     (hardcoded by Supabase test_otp config)

Prereqs:
    - Supabase running locally (`make infra`)
    - Real Alpaca sandbox creds in `.env`

Idempotent: re-running with the same alpaca_account_id is a no-op aside
from refreshing `account_status=ACTIVE` and `updated_at`. Re-running with
a different alpaca_account_id repoints the existing user.
"""

import asyncio
import sys
import uuid
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

# Matches the test_otp pattern Supabase is configured to short-circuit:
# phone = 15551234567, otp = 123456. iOS submits this combo and skips SMS.
TEST_PHONE = "+15551234567"
TEST_EMAIL = "portfolio-e2e@sevino.test"


def _get_or_create_user_by_phone() -> str:
    """Return auth.users id for TEST_PHONE, creating via admin API if needed."""
    headers = {
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "apikey": SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }

    # The admin list endpoint paginates. Pull the first 200 users and match.
    resp = httpx.get(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        params={"page": 1, "per_page": 200},
    )
    resp.raise_for_status()
    for u in resp.json().get("users", []):
        if u.get("phone") == TEST_PHONE.lstrip("+"):
            return u["id"]
        if u.get("phone") == TEST_PHONE:
            return u["id"]

    # Create — pre-confirm phone so the iOS OTP flow doesn't have to verify
    # again; it just authenticates against the existing user.
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        json={
            "phone": TEST_PHONE,
            "email": TEST_EMAIL,
            "phone_confirm": True,
            "email_confirm": True,
        },
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase admin create user failed: {resp.status_code} {resp.text}")
    return resp.json()["id"]


async def _link_alpaca_account(user_id: str, alpaca_account_id: str) -> None:
    """Insert user_profiles + brokerage_accounts; set account_status=ACTIVE."""
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
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
            TEST_EMAIL,
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
                activated_at = COALESCE(brokerage_accounts.activated_at, now()),
                updated_at = now()
            """,
            uuid.uuid4(),
            user_uuid,
            alpaca_account_id,
        )
    finally:
        await conn.close()


async def main(alpaca_account_id: str) -> int:
    print(f"→ ensuring phone-OTP test user ({TEST_PHONE}) exists")
    user_id = _get_or_create_user_by_phone()
    print(f"  user_id = {user_id}")

    print(f"→ linking brokerage_accounts → {alpaca_account_id}")
    await _link_alpaca_account(user_id, alpaca_account_id)

    print()
    print("✓ ready")
    print()
    print("On the iOS simulator, sign in with:")
    print(f"  phone:  {TEST_PHONE.lstrip('+')}")
    print(f"  OTP:    123456")
    print()
    print("The holdings modal should pull positions from the Alpaca account above.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
