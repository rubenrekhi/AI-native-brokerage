"""Seed a local test user + ACTIVE Alpaca sandbox brokerage account, mint a JWT.

Paired with `scripts/funding_smoke.sh`. Creates (or re-uses) everything the
funding smoke test needs, then writes `scripts/.funding_smoke_env` for the
shell script to source.

Run:
    uv run python scripts/seed_funding_sandbox.py

Prereqs:
    - Supabase + Redis running locally (`make infra`)
    - Real Plaid sandbox + Alpaca sandbox credentials in `.env`

Idempotent: safe to re-run. Reuses the existing Alpaca sandbox account if it's
still valid, otherwise creates a fresh one. Always returns a new JWT.
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
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)

TEST_EMAIL = "funding-smoke@sevino.test"
TEST_PASSWORD = "funding-smoke-pw-!123"


def _get_or_create_user() -> str:
    """Return the auth.users id for TEST_EMAIL, creating via admin API if needed."""
    headers = {
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "apikey": SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }

    # List users and match by email — /admin/users is a paginated list endpoint.
    resp = httpx.get(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        params={"page": 1, "per_page": 100},
    )
    resp.raise_for_status()
    for u in resp.json().get("users", []):
        if u.get("email") == TEST_EMAIL:
            return u["id"]

    # Create
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "email_confirm": True,
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def _ensure_alpaca_sandbox_account(alpaca_api_key: str, alpaca_secret: str) -> str:
    """Create a minimal Alpaca sandbox account via the Broker API.

    Returns the real `alpaca_account_id`. Sandbox accounts auto-approve within
    seconds. We always create a fresh one per run since Alpaca sandbox doesn't
    easily let us look up by our own key.
    """
    # OAuth2 client_credentials
    auth_resp = httpx.post(
        "https://authx.sandbox.alpaca.markets/v1/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": alpaca_api_key,
            "client_secret": alpaca_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    auth_resp.raise_for_status()
    token = auth_resp.json()["access_token"]

    suffix = uuid.uuid4().hex[:8]
    payload = {
        "contact": {
            "email_address": f"smoke-{suffix}@sevino.test",
            "phone_number": "+15551234567",
            "street_address": ["123 Main St"],
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94111",
            "country": "USA",
        },
        "identity": {
            "given_name": "Smoke",
            "family_name": f"Tester{suffix}",
            "date_of_birth": "1990-01-01",
            "tax_id": "555-37-8210",
            "tax_id_type": "USA_SSN",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income"],
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
        },
        "agreements": [
            {
                "agreement": "customer_agreement",
                "signed_at": "2026-04-19T00:00:00Z",
                "ip_address": "127.0.0.1",
            },
            {
                "agreement": "margin_agreement",
                "signed_at": "2026-04-19T00:00:00Z",
                "ip_address": "127.0.0.1",
            },
        ],
    }
    resp = httpx.post(
        "https://broker-api.sandbox.alpaca.markets/v1/accounts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Alpaca account create failed: {resp.status_code} {resp.text}")
    return resp.json()["id"]


async def _ensure_profile_and_active_brokerage(
    user_id: str, alpaca_account_id: str
) -> None:
    """Insert user_profiles + brokerage_accounts if missing; force status=ACTIVE
    and update alpaca_account_id."""
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


async def _cleanup_local_rows(user_id: str) -> None:
    """Mark local plaid_items + ach_relationships stale so the next smoke starts clean."""
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    try:
        uid = uuid.UUID(user_id)
        await conn.execute(
            "UPDATE ach_relationships SET status='CANCELED' WHERE user_id=$1 AND status!='CANCELED'",
            uid,
        )
        await conn.execute(
            "UPDATE plaid_items SET status='inactive' WHERE user_id=$1 AND status='active'",
            uid,
        )
    finally:
        await conn.close()


def _sign_in_for_jwt() -> tuple[str, str]:
    """Returns (access_token, refresh_token). Uses gotrue's password grant."""
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    resp.raise_for_status()
    body = resp.json()
    return body["access_token"], body["refresh_token"]


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


async def main() -> int:
    env = _read_env_file()
    plaid_id = env.get("PLAID_CLIENT_ID", "")
    plaid_secret = env.get("PLAID_SECRET", "")
    alpaca_key = env.get("ALPACA_API_KEY", "")
    alpaca_secret = env.get("ALPACA_SECRET_KEY", "")
    if not plaid_id or plaid_id.startswith("your-"):
        print("ERROR: PLAID_CLIENT_ID missing or placeholder in .env", file=sys.stderr)
        return 1
    if not alpaca_key or alpaca_key.startswith("your-"):
        print("ERROR: ALPACA_API_KEY missing or placeholder in .env", file=sys.stderr)
        return 1

    print("→ ensuring test user in auth.users")
    user_id = _get_or_create_user()
    print(f"  user_id = {user_id}")

    # Always create a fresh Alpaca sandbox account. Reusing across runs hits
    # Alpaca's "1 ACH transfer per direction per trading day" sandbox limit;
    # sandbox accounts are cheap and there's no cleanup obligation.
    print("→ creating fresh Alpaca sandbox brokerage account")
    alpaca_account_id = await _ensure_alpaca_sandbox_account(alpaca_key, alpaca_secret)
    print(f"  alpaca_account_id = {alpaca_account_id}")

    print("→ upserting user_profiles + ACTIVE brokerage_accounts")
    await _ensure_profile_and_active_brokerage(user_id, alpaca_account_id)

    print("→ soft-canceling any leftover local plaid_items + ach_relationships")
    await _cleanup_local_rows(user_id)

    print("→ signing in for a fresh JWT")
    access_token, _ = _sign_in_for_jwt()

    out_path = Path(__file__).parent / ".funding_smoke_env"
    out_path.write_text(
        "# Source this before running phase8_smoke.sh\n"
        f"export TEST_USER_ID='{user_id}'\n"
        f"export TEST_EMAIL='{TEST_EMAIL}'\n"
        f"export ALPACA_ACCOUNT_ID='{alpaca_account_id}'\n"
        f"export JWT='{access_token}'\n"
        f"export PLAID_CLIENT_ID='{plaid_id}'\n"
        f"export PLAID_SECRET='{plaid_secret}'\n"
        f"export API_KEY='{env.get('API_KEY', '')}'\n"
        f"export BACKEND_URL='http://localhost:8000'\n"
        f"export PLAID_WEBHOOK_URL='{env.get('PLAID_WEBHOOK_URL', '')}'\n"
    )
    out_path.chmod(0o600)
    print(f"✓ wrote {out_path}")
    print()
    print("Next:")
    print(f"  1. make server   (run in another terminal)")
    print(f"  2. source scripts/.funding_smoke_env")
    print(f"  3. bash scripts/funding_smoke.sh")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
