# Onboarding & KYC Backend — Implementation Plan

## Context

The Saturn iOS app has a 28-screen onboarding flow (documented in `saturn-api/docs/onboarding.md`) split into two phases:
- **Phase 1 (screens 1-18):** Profile building — name, worries, goals, DOB, income, net worth, risk tolerance, experience.
- **Phase 2 (screens 19-28):** KYC / Alpaca account creation — legal name, SSN, address, citizenship, employment, disclosures, agreements.

The frontend persists data to the backend **after every step** so users can resume mid-flow if they close the app. At the end, a submit endpoint loads all saved data, combines it with the SSN (the one field we never store), builds the Alpaca payload with all derived fields, and creates the brokerage account.

The models (`user_profiles`, `user_financial_profiles`, `brokerage_accounts`) already exist with most fields. Routes and services directories are empty — this is the first feature built on top of the infrastructure.

---

## Screen-by-Screen Data Map

### Phase 1 — Profile Building (screens 1-18)

All Phase 1 data is **stored in our DB**. Nothing is pass-through.

| Screen | Data | Stored in | Alpaca use |
|---|---|---|---|
| 1 — Welcome | (none) | — | — |
| 2 — First Name | `preferred_name` | `user_profiles.preferred_name` | Pre-fills `identity.given_name` |
| 3 — Attribution | `attribution_source` | `user_profiles.attribution_source` *(new)* | None — internal analytics |
| 4 — Financial Worry | `financial_worries[]` | `user_financial_profiles.financial_worries` | None — AI context only |
| 5 — Reflection | (none) | — | — |
| 6 — Financial Goals | `investment_goals[]` | `user_financial_profiles.investment_goals` | Derived → `investment_objective` |
| 7 — Reflection | (none) | — | — |
| 8 — Date of Birth | `date_of_birth` | `user_profiles.date_of_birth` | `identity.date_of_birth` |
| 9 — Annual Income | `annual_income` | `user_financial_profiles.annual_income` | Derived → `annual_income_min/max` |
| 10 — Total Net Worth | `net_worth` | `user_financial_profiles.net_worth` | Derived → `total_net_worth_min/max` |
| 11 — Liquid Net Worth | `liquid_net_worth` | `user_financial_profiles.liquid_net_worth` | Derived → `liquid_net_worth_min/max` |
| 12 — Income Stability | `income_stability` | `user_financial_profiles.income_stability` | None — AI context only |
| 13 — Time Horizon | `time_horizon` | `user_financial_profiles.time_horizon` | Derived → `investment_time_horizon` + `liquidity_needs` |
| 14 — Risk Scenario | `risk_scenario_response` | `user_financial_profiles.risk_scenario_response` | Combined w/ screen 15 → `risk_tolerance` |
| 15 — Max Loss | `max_loss_tolerance` | `user_financial_profiles.max_loss_tolerance` | Combined w/ screen 14 → `risk_tolerance` |
| 16 — Experience | `experience_level` | `user_financial_profiles.experience_level` | Derived → `investment_experience_with_stocks` |
| 17 — Compounding Chart | (none) | — | — |
| 18 — Risk Disclosure | acknowledgment timestamp | `user_profiles.risk_disclosure_acknowledged_at` *(new)* | None — compliance record |

### Phase 2 — KYC (screens 19-28)

All data is **stored** except SSN which is **pass-through only**.

| Screen | Data | Stored? | Where | Alpaca mapping |
|---|---|---|---|---|
| 19 — KYC Intro | (none) | — | — | — |
| 20 — Legal Name | first_name, middle_name, last_name | **Yes** | `user_profiles` | `identity.given_name/middle_name/family_name` |
| 21 — SSN | tax_id | **No** — pass-through | Only in submit request body | `identity.tax_id` + `tax_id_type: USA_SSN` |
| 22 — Address | street_address[], city, state, postal_code | **Yes** | `user_profiles` *(new columns)* | `contact.street_address/city/state/postal_code` |
| 23 — Citizenship | country_of_citizenship, country_of_birth, country_of_tax_residence | **Yes** | `user_profiles` *(new columns)* | `identity.country_of_*` |
| 24 — Employment | employment_status, employer_name, job_title | **Yes** | `user_financial_profiles.employment_info` (JSONB) | `identity.employment_status` (mapped) |
| 25 — Funding Sources | funding_sources[] | **Yes** | `user_financial_profiles.funding_sources` | `identity.funding_source[]` |
| 26 — Disclosures | is_control_person, is_affiliated, is_politically_exposed, immediate_family_exposed | **Yes** | `user_profiles.disclosures` *(new JSONB)* | `disclosures.*` |
| 27 — Agreements | customer_agreement, margin_agreement + signed_at, ip_address | **Yes** | `user_profiles.agreements_signed` *(new JSONB)* | `agreements[]` |
| 28 — Submit | triggers Alpaca submission | — | — | Full payload constructed |

**SSN flow:** Screen 21 data is held in the iOS app's memory only. The frontend does NOT call PATCH for screen 21. When the user hits submit (screen 28), the SSN is sent in the `POST /v1/onboarding/submit` body. The backend holds it in memory, forwards it to Alpaca, and never writes it to the database.

---

## API Endpoints

All require auth (`Depends(get_current_user)`), prefix `/v1/onboarding`.

### 1. `PATCH /v1/onboarding`
Incremental save — called after every screen with user input. Accepts all profile + financial + KYC fields as optional. Only provided fields are updated.

**Request body** (all fields optional):
```python
class OnboardingPatchRequest(BaseModel):
    step: OnboardingStep                         # validated enum (see schemas/onboarding.py)

    # Phase 1 — user_profiles fields
    preferred_name: str | None = None
    date_of_birth: date | None = None
    phone_number: str | None = None
    attribution_source: str | None = None
    risk_disclosure_acknowledged_at: datetime | None = None

    # Phase 1 — user_financial_profiles fields
    financial_worries: list[str] | None = None
    investment_goals: list[str] | None = None
    annual_income: str | None = None
    net_worth: str | None = None
    liquid_net_worth: str | None = None
    income_stability: str | None = None
    time_horizon: str | None = None
    risk_scenario_response: str | None = None
    max_loss_tolerance: str | None = None
    experience_level: str | None = None

    # Phase 2 — user_profiles fields (KYC)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    street_address: list[str] | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country_of_citizenship: str | None = None
    country_of_birth: str | None = None
    country_of_tax_residence: str | None = None

    # Phase 2 — user_financial_profiles fields
    employment_info: dict | None = None          # {status, employer_name, job_title}
    funding_sources: list[str] | None = None

    # Phase 2 — JSONB on user_profiles
    disclosures: dict | None = None              # {is_control_person, ...}
    agreements_signed: dict | None = None        # {customer_agreement, margin_agreement, signed_at, ip_address}
```

**Actions:**
1. Route each provided field to the correct table (`user_profiles` or `user_financial_profiles`)
2. For `user_financial_profiles`: create the row if it doesn't exist yet (first financial field saved)
3. Update `user_profiles.onboarding_step` with the `step` value
4. Return 200 with `{ "step": "<step>" }`

### 2. `POST /v1/onboarding/submit`
Final submission — creates the Alpaca brokerage account.

**Request body:**
```python
class OnboardingSubmitRequest(BaseModel):
    tax_id: str              # SSN — forwarded to Alpaca, NEVER stored
    tax_id_type: str = "USA_SSN"
```

**Actions:**
1. Validate no existing `brokerage_accounts` row for this user (409 if exists)
2. Load `user_profiles` + `user_financial_profiles` from DB
3. Validate all required fields are present (name, DOB, address, citizenship, disclosures, agreements, financial profile)
4. Build the full Alpaca `POST /v1/accounts` payload (see detailed construction below)
5. Call Alpaca Broker API
6. Create `brokerage_accounts` row with `alpaca_account_id`, `account_status`, `kyc_submitted_at`
7. Set `onboarding_step = "submitted"`
8. Return `{ "account_status": "SUBMITTED", "alpaca_account_id": "..." }`

### 3. `GET /v1/onboarding/status`
Returns full onboarding state + all saved data for resume.

**Response:**
```json
{
  "onboarding_completed": false,
  "onboarding_step": "address",
  "account_status": null,
  "kyc_results": null,
  "profile": {
    "preferred_name": "Riley",
    "date_of_birth": "1998-03-15",
    "first_name": "Riley",
    "last_name": "Johnson",
    "street_address": ["123 Main St"],
    "city": "New York",
    "...": "all saved user_profiles fields"
  },
  "financial_profile": {
    "financial_worries": ["not_saving_enough"],
    "investment_goals": ["grow_wealth"],
    "annual_income": "$50K-$100K",
    "...": "all saved user_financial_profiles fields"
  }
}
```

---

## Alpaca Payload Construction — Full Detail

When `POST /v1/onboarding/submit` is called, the service builds the Alpaca `POST /v1/accounts` payload by combining stored DB data with the incoming SSN. Every derived field is computed server-side.

### Final Alpaca Payload Structure

```json
{
  "contact": {
    "email_address": "<from user_profiles.email>",
    "phone_number": "<from user_profiles.phone_number>",
    "street_address": ["123 Main St"],
    "city": "New York",
    "state": "NY",
    "postal_code": "10001"
  },
  "identity": {
    "given_name": "Riley",
    "middle_name": "James",
    "family_name": "Johnson",
    "date_of_birth": "1998-03-15",
    "tax_id": "123-45-6789",
    "tax_id_type": "USA_SSN",
    "country_of_citizenship": "USA",
    "country_of_birth": "USA",
    "country_of_tax_residence": "USA",
    "funding_source": ["employment_income", "savings"],
    "annual_income_min": "50000",
    "annual_income_max": "100000",
    "total_net_worth_min": "50000",
    "total_net_worth_max": "100000",
    "liquid_net_worth_min": "25000",
    "liquid_net_worth_max": "50000",
    "investment_time_horizon": "6_to_10_years",
    "liquidity_needs": "does_not_matter",
    "investment_experience_with_stocks": "1_to_5_years",
    "investment_experience_with_options": "none",
    "risk_tolerance": "moderate",
    "investment_objective": "growth",
    "employment_status": "employed"
  },
  "disclosures": {
    "is_control_person": false,
    "is_affiliated_exchange_or_finra": false,
    "is_politically_exposed": false,
    "immediate_family_exposed": false
  },
  "agreements": [
    {
      "agreement": "customer_agreement",
      "signed_at": "2026-04-06T12:00:00Z",
      "ip_address": "1.2.3.4"
    },
    {
      "agreement": "margin_agreement",
      "signed_at": "2026-04-06T12:00:00Z",
      "ip_address": "1.2.3.4"
    }
  ]
}
```

### Derived Field Logic — Complete Reference

All mapping logic lives in `app/services/onboarding.py` as pure functions.

#### 1. Annual Income → `annual_income_min` / `annual_income_max`

The frontend sends a range string from screen 9. The backend maps it to Alpaca's min/max bracket values.

```python
INCOME_RANGES = {
    "Under $25K":     ("0", "25000"),
    "$25K-$50K":      ("25000", "50000"),
    "$50K-$100K":     ("50000", "100000"),
    "$100K-$200K":    ("100000", "200000"),
    "$200K-$500K":    ("200000", "500000"),
    "$500K+":         ("500000", "1000000"),
}
```

#### 2. Total Net Worth → `total_net_worth_min` / `total_net_worth_max`

```python
NET_WORTH_RANGES = {
    "Under $10K":     ("0", "10000"),
    "$10K-$50K":      ("10000", "50000"),
    "$50K-$100K":     ("50000", "100000"),
    "$100K-$250K":    ("100000", "250000"),
    "$250K-$500K":    ("250000", "500000"),
    "$500K-$1M":      ("500000", "1000000"),
    "$1M+":           ("1000000", "5000000"),
}
```

#### 3. Liquid Net Worth → `liquid_net_worth_min` / `liquid_net_worth_max`

```python
LIQUID_NET_WORTH_RANGES = {
    "Under $10K":     ("0", "10000"),
    "$10K-$25K":      ("10000", "25000"),
    "$25K-$50K":      ("25000", "50000"),
    "$50K-$100K":     ("50000", "100000"),
    "$100K-$250K":    ("100000", "250000"),
    "$250K+":         ("250000", "1000000"),
}
```

#### 4. Time Horizon → `investment_time_horizon` + `liquidity_needs`

From screen 13. Two Alpaca fields derived from one user selection.

```python
TIME_HORIZON_MAP = {
    "Less than 2 years": ("1_to_2_years", "very_important"),
    "2 – 5 years":       ("3_to_5_years", "somewhat_important"),
    "5 – 10 years":      ("6_to_10_years", "does_not_matter"),
    "10 – 20 years":     ("more_than_10_years", "does_not_matter"),
    "20+ years":         ("more_than_10_years", "does_not_matter"),
}

def map_time_horizon(time_horizon: str) -> tuple[str, str]:
    """Returns (investment_time_horizon, liquidity_needs)."""
    return TIME_HORIZON_MAP[time_horizon]
```

#### 5. Risk Tolerance — Combined Mapping Matrix (screens 14 + 15)

This is the most complex derivation. Two user answers are combined using a mapping matrix from the onboarding doc.

**Screen 14 — risk_scenario_response** (what the user would do if portfolio dropped 25%):
- `"sell_everything"` — Sell everything immediately
- `"sell_some"` — Sell some
- `"hold"` — Hold and do nothing
- `"buy_more"` — Buy more while prices are low
- `"not_sure"` — Not sure

**Screen 15 — max_loss_tolerance** (how much decline they can handle):
- `"0-5%"`
- `"5-15%"`
- `"15-25%"`
- `"25-40%"`
- `"40%+"`

**Mapping matrix** → Alpaca `identity.risk_tolerance`:

```python
def derive_risk_tolerance(scenario: str, max_loss: str) -> str:
    """
    Mapping matrix from onboarding doc (screens 14 + 15):

    | Scenario Response          | Max Drop       | → risk_tolerance |
    |----------------------------|----------------|------------------|
    | sell_everything / sell_some | 0-5% or 5-15%  | conservative     |
    | sell_everything / sell_some | 15-25% or above | moderate        |
    | hold / not_sure            | 0-5% or 5-15%  | conservative     |
    | hold / not_sure            | 15-25% or above | moderate        |
    | buy_more                   | 0-5% to 15-25% | moderate         |
    | buy_more                   | 25-40% or 40%+ | significant_risk |
    """
    low_loss = max_loss in ("0-5%", "5-15%")
    high_loss = max_loss in ("25-40%", "40%+")

    if scenario in ("sell_everything", "sell_some"):
        return "conservative" if low_loss else "moderate"
    elif scenario in ("hold", "not_sure"):
        return "conservative" if low_loss else "moderate"
    elif scenario == "buy_more":
        return "significant_risk" if high_loss else "moderate"

    return "moderate"  # fallback
```

#### 6. Investment Goals → `investment_objective`

From screen 6. The user's first selected goal determines the Alpaca value.

**Screen 6 options:**
1. `"grow_wealth"` — Grow my wealth over time
2. `"save_for_goal"` — Save for a big goal
3. `"retirement"` — Get on track for retirement
4. `"safety_net"` — Build a safety net beyond savings
5. `"learn_to_invest"` — Learn to invest with real money
6. `"make_cash_work"` — Make my cash work harder

```python
def derive_investment_objective(goals: list[str]) -> str:
    """
    From onboarding doc screen 6 → Alpaca investment_objective.
    Based on the FIRST selected goal (priority order).

    Options 1, 2, 3, 5 → "growth"
    Options 4, 6       → "preserve_wealth"
    """
    GOAL_MAP = {
        "grow_wealth": "growth",
        "save_for_goal": "growth",
        "retirement": "growth",
        "safety_net": "preserve_wealth",
        "learn_to_invest": "growth",
        "make_cash_work": "preserve_wealth",
    }
    for goal in goals:
        if goal in GOAL_MAP:
            return GOAL_MAP[goal]
    return "growth"  # fallback
```

#### 7. Experience Level → `investment_experience_with_stocks`

From screen 16.

**Screen 16 options:**
1. `"never_invested"` — I've never really invested
2. `"invested_little"` — I've invested a little, but not actively
3. `"invest_regularly"` — I invest regularly in stocks or funds
4. `"actively_manage"` — I actively manage my portfolio and follow markets
5. `"advanced_strategies"` — I've tried advanced strategies like options or crypto

```python
EXPERIENCE_MAP = {
    "never_invested": "none",
    "invested_little": "1_to_5_years",
    "invest_regularly": "1_to_5_years",
    "actively_manage": "over_5_years",
    "advanced_strategies": "over_5_years",
}
```

`investment_experience_with_options` is always hardcoded to `"none"`.

#### 8. Employment Status Mapping

From screen 24. The `employment_info` JSONB stores the raw data. For Alpaca, we map the status to their enum.

```python
EMPLOYMENT_STATUS_MAP = {
    "employed": "employed",
    "self_employed": "employed",
    "unemployed": "unemployed",
    "student": "student",
    "retired": "retired",
}
```

#### 9. Funding Sources

From screen 25. Stored as-is — the frontend sends values that match Alpaca's expected format.

```python
# Accepted values (match Alpaca's funding_source enum):
# "employment_income", "savings", "investments",
# "business_income", "family", "inheritance"
```

#### 10. Agreements Array Construction

From screen 27's stored `agreements_signed` JSONB:

```python
def build_agreements(agreements_data: dict) -> list[dict]:
    """
    Constructs the agreements array for Alpaca.
    agreements_data contains: customer_agreement (bool), margin_agreement (bool),
    signed_at (ISO timestamp), ip_address (str)
    """
    result = []
    if agreements_data.get("customer_agreement"):
        result.append({
            "agreement": "customer_agreement",
            "signed_at": agreements_data["signed_at"],
            "ip_address": agreements_data["ip_address"],
        })
    if agreements_data.get("margin_agreement"):
        result.append({
            "agreement": "margin_agreement",
            "signed_at": agreements_data["signed_at"],
            "ip_address": agreements_data["ip_address"],
        })
    return result
```

---

## Model Changes

### `user_profiles` — add columns:

| Column | Type | Notes |
|---|---|---|
| `middle_name` | Text, nullable | Legal middle name (screen 20) |
| `phone_number` | Text, nullable | From registration, needed for Alpaca contact |
| `street_address` | ARRAY(Text), nullable | Address lines (screen 22) |
| `city` | Text, nullable | Screen 22 |
| `state` | Text, nullable | 2-letter state code (screen 22) |
| `postal_code` | Text, nullable | Screen 22 |
| `country_of_citizenship` | Text, nullable | Screen 23, default USA |
| `country_of_birth` | Text, nullable | Screen 23, default USA |
| `country_of_tax_residence` | Text, nullable | Screen 23, default USA |
| `disclosures` | JSONB, nullable | FINRA disclosure answers (screen 26) |
| `agreements_signed` | JSONB, nullable | Agreement records with signed_at + ip_address (screen 27) |
| `attribution_source` | Text, nullable | How they found Sevino (screen 3) |
| `risk_disclosure_acknowledged_at` | DateTime(timezone=True), nullable | Compliance timestamp (screen 18) |

No changes to `user_financial_profiles` or `brokerage_accounts` — existing fields cover everything needed.

---

## Architecture Layers

```
Routes (app/routes/)          → HTTP handling, auth, validation
    ↓
Services (app/services/)      → business logic, Alpaca payload construction, derivation logic
    ↓
Repositories (app/repositories/)  → all SQLAlchemy queries (select, insert, update)
    ↓
Models (app/models/)          → SQLAlchemy ORM definitions
```

**Per-table repositories** — each repo owns one table's access patterns. Reusable across features (e.g. `UserProfileRepository` is used by onboarding now, settings later, AI context loader later). The service layer orchestrates across repos for feature-specific logic.

---

## Files to Create

### `app/repositories/__init__.py`
Empty init for the repositories package.

### `app/repositories/user_profile.py`
`UserProfileRepository` — CRUD for `user_profiles` table.
- `get_by_id(db, user_id) → UserProfile | None`
- `update_fields(db, user_id, **fields) → UserProfile` — partial update, only sets provided fields. Always updates `updated_at`. Used by the PATCH endpoint to save whichever profile fields came in.

### `app/repositories/financial_profile.py`
`FinancialProfileRepository` — CRUD for `user_financial_profiles` table.
- `get_by_user_id(db, user_id) → UserFinancialProfile | None`
- `upsert(db, user_id, **fields) → UserFinancialProfile` — creates the row if it doesn't exist (first financial field saved during onboarding), updates if it does. Only sets provided fields.

### `app/repositories/brokerage_account.py`
`BrokerageAccountRepository` — CRUD for `brokerage_accounts` table.
- `get_by_user_id(db, user_id) → BrokerageAccount | None`
- `create(db, user_id, alpaca_account_id, account_status, **fields) → BrokerageAccount`
- `update_status(db, account_id, status, **fields) → BrokerageAccount` — used by KYC polling task
- `get_pending() → list[BrokerageAccount]` — accounts with status IN ('SUBMITTED', 'ACTION_REQUIRED'), used by polling task

### `app/schemas/__init__.py`
Empty init for the schemas package.

### `app/schemas/onboarding.py`
Pydantic models:
- `OnboardingPatchRequest` — flexible partial-update model (all fields optional except `step`)
- `OnboardingSubmitRequest` — just `tax_id` + `tax_id_type`
- `OnboardingStatusResponse` — full state including saved profile/financial data
- Nested models for structured fields: `DisclosuresInput`, `AgreementsInput`, `EmploymentInfoInput`

### `app/services/alpaca_broker.py`
Alpaca Broker API client using `httpx`:
- OAuth2 Client Credentials auth via `authx.sandbox.alpaca.markets` (exchanges client ID + secret for Bearer token, cached ~15 min)
- Sandbox: `https://broker-api.sandbox.alpaca.markets` (dev/staging)
- Prod: `https://broker-api.alpaca.markets`
- Persistent `httpx.AsyncClient` — created once in `lifecycle.py`, stored on `app.state.alpaca`
- `create_account(payload: dict) → dict` — POST /v1/accounts
- `get_account(account_id: str) → dict` — GET /v1/accounts/{id}
- `update_account(account_id: str, payload: dict) → dict` — PATCH /v1/accounts/{id}
- Defines `AlpacaBrokerError` (API errors) and `AlpacaBrokerUnavailableError` (network errors) — both caught by global exception handlers

### `app/services/onboarding.py`
Orchestration service + all derivation logic. Calls repositories, never touches `db.execute()` directly.
- `save_step(user_id, data, db)` — routes fields to correct repos (`UserProfileRepository.update_fields()` + `FinancialProfileRepository.upsert()`), updates onboarding_step
- `submit_kyc(user_id, tax_id, tax_id_type, db, alpaca_client)` — loads data via repos, validates completeness, builds payload, calls Alpaca, creates brokerage row via `BrokerageAccountRepository.create()`
- `get_status(user_id, db)` — loads state from all 3 repos
- `build_alpaca_payload(profile, financial_profile, tax_id, tax_id_type)` — constructs the complete Alpaca POST body
- All mapping constants and derivation functions (risk_tolerance, income ranges, etc.)
- `validate_completeness(profile, financial_profile)` — checks all required fields present before submission

### `app/routes/onboarding.py`
FastAPI router with 3 endpoints. Depends on `get_current_user` + `get_db`. Calls service layer only — no direct DB access.

### `tests/fixtures/mock_responses/alpaca_account.json`
Sample Alpaca `POST /v1/accounts` response.

> **Note:** KYC status polling / SSE listener is out of scope for this branch. `onboarding_completed` remains `false` after submission — it will flip to `true` when the SSE listener is built and Alpaca approves the account.

---

## Files to Modify

| File | Change |
|---|---|
| `app/models/user_profile.py` | Add 13 new columns (see Model Changes above) + new imports (ARRAY, JSONB, DateTime) |
| `app/main.py` | `from app.routes.onboarding import router as onboarding_router` + `app.include_router(onboarding_router, prefix="/v1/onboarding", tags=["onboarding"])` |
| `app/config.py` | Add `alpaca_base_url` and `alpaca_auth_url` properties (sandbox vs prod) |
| `app/lifecycle.py` | Init `AlpacaBrokerService` on `app.state.alpaca` during startup |

### Migration
`make migration msg="add onboarding fields to user_profiles"` — adds 13 new nullable columns. No data migration needed.

---

## Tests

### Unit tests (`tests/unit/test_onboarding_service.py`)
- `build_alpaca_payload` produces correct full structure
- All range mapping functions (income, net worth, liquid net worth) — every bracket
- Risk tolerance mapping matrix — all 15 combinations from the doc
- Investment objective derivation — all 6 goal types
- Experience level mapping — all 5 options
- Time horizon → (investment_time_horizon, liquidity_needs) — all 5 options
- Employment status mapping
- Agreements array construction (customer only, both, etc.)
- `validate_completeness` — catches missing required fields
- `save_step` routes fields to correct repos (mock repos, verify calls)
- `submit_kyc` orchestration (mock repos + Alpaca client, verify full flow)

### Unit tests (`tests/unit/test_alpaca_broker.py`)
- Auth header constructed correctly (base64 Basic auth)
- URL routing (sandbox vs prod based on environment)
- Error response handling (400, 403, 422, 429, 500 → correct exceptions)

### Integration tests (`tests/integration/test_onboarding.py`)
- `PATCH /v1/onboarding` — saves Phase 1 field, returns 200
- `PATCH /v1/onboarding` — saves Phase 2 field (address), returns 200
- `PATCH /v1/onboarding` — creates `user_financial_profiles` row on first financial field
- `PATCH /v1/onboarding` — unauthenticated → 401
- `POST /v1/onboarding/submit` — mocked Alpaca, creates brokerage row, returns status
- `POST /v1/onboarding/submit` — duplicate submission → 409
- `POST /v1/onboarding/submit` — missing required fields → 422
- `GET /v1/onboarding/status` — returns saved data for resume
- `GET /v1/onboarding/status` — no data yet → returns empty profile

### Test fixtures
- `tests/fixtures/mock_responses/alpaca_account.json` — successful account creation response

---

## Verification

1. `make test-unit` — all new unit tests pass
2. `uv run pytest tests/integration/test_onboarding.py` — integration tests pass
3. `uv run alembic heads` — single head (no migration conflicts)
4. `make test` — full suite, no regressions
