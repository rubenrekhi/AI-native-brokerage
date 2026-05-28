# Alpaca Broker API Integration Architecture

> **Sevino Technical Reference Document** — Version 1.0 • March 2026
>
> This document defines how the Sevino mobile application integrates with Alpaca's Broker API. It maps each feature to specific Alpaca endpoints, communication protocols (REST, SSE), and data flows. Use this as the single source of truth for the entire brokerage integration layer.

---

## Key Architectural Principles

- **The mobile app NEVER communicates directly with Alpaca.** All Alpaca API calls originate from the Sevino backend.
- **Broker API authentication uses Sevino's firm-level API keys**, not individual user credentials.
- **The backend is the single source of truth** for all account, position, and order state.
- **Fully disclosed broker structure**: each end user gets their own Alpaca brokerage account.
- Alpaca Securities LLC is a FINRA-member, SIPC-protected, self-clearing broker-dealer.

**Alpaca API Reference:** https://docs.alpaca.markets/reference/api-references

---

## Communication Protocols

Sevino uses two communication mechanisms with Alpaca's Broker API. Each serves a different purpose.

### REST API (Request/Response)

The primary mechanism for reading data and initiating actions. Every account creation, order placement, position query, and market data lookup is a synchronous HTTP call.

| Property | Value |
|---|---|
| **Sandbox Base URL** | `https://broker-api.sandbox.alpaca.markets` |
| **Production Base URL** | `https://broker-api.alpaca.markets` |
| **Authentication** | OAuth2 Client Credentials — exchange client ID + secret for a short-lived Bearer token (see below) |
| **Auth Token URL (Sandbox)** | `https://authx.sandbox.alpaca.markets/v1/oauth2/token` |
| **Auth Token URL (Production)** | `https://authx.alpaca.markets/v1/oauth2/token` |

### Server-Sent Events (SSE)

Server-to-server event streaming for asynchronous state changes. The Sevino backend opens persistent HTTP connections to Alpaca's Events API and receives pushed updates (account approvals, transfer completions, order fills / cancels / rejects).

- Supports both real-time streaming and historical queries.
- On connection drop, reconnect and replay missed events using `since_ulid` / `since_id` parameters.
- Alpaca's Broker API allows **up to 25 concurrent SSE connections per API key** ([Broker API FAQ](https://docs.alpaca.markets/docs/broker-api-faq)); exceeded requests return `Too many requests`. See `docs/architecture.md` §Worker topology for how that pool is allocated across environments.

### Note on WebSockets

Alpaca's Broker API does not expose a WebSocket trade-updates endpoint. The `wss://(paper-)api.alpaca.markets/stream` WebSockets belong to Alpaca's **Trading API** (different auth model, different concurrency rules, per-account rather than broker-wide). As a broker partner, Sevino uses the Broker API's SSE trade events stream (`/v2/events/trades`) for all real-time order status updates.

The Market Data WebSocket (`wss://stream.data.alpaca.markets/v2/{feed}`) is a separate feature — available but deferred to future; see §Future Enhancements.

### Protocol Decision Matrix

Use this table to determine which protocol to use for each data type:

| Data Type | Protocol | Direction | Frequency |
|---|---|---|---|
| Account creation / KYC submission | REST | Sevino → Alpaca | One-time per user |
| Account status changes (KYC approval) | SSE | Alpaca → Sevino | Per event |
| ACH transfer initiation | REST | Sevino → Alpaca | Per transfer |
| Transfer status updates | SSE | Alpaca → Sevino | Per event |
| Position / holdings queries | REST | Sevino → Alpaca | On demand (user opens modal) |
| Account info (balance, buying power) | REST | Sevino → Alpaca | On demand + 5-min background |
| Portfolio history (charts) | REST | Sevino → Alpaca | On demand (user opens modal) |
| Order placement | REST | Sevino → Alpaca | Per trade |
| Order fill / cancel / reject events | SSE | Alpaca → Sevino | Per event |
| Stock prices (Stock Info Cards, Radar) | REST | Sevino → Alpaca | On demand (user taps) |
| Historical bars (sparklines, charts) | REST | Sevino → Alpaca | On demand (user taps) |
| Market clock / calendar | REST | Sevino → Alpaca | On app open / new conversation |
| FDIC Sweep enrollment | REST | Sevino → Alpaca | One-time per user |
| Interest data (APY, accrued) | REST | Sevino → Alpaca | On demand |

---

## Account Creation & KYC

**PRD References:** FR-3.1, FR-3.2, FR-1.5, FR-1.6

Account creation follows a two-phase pattern: synchronous REST submission, then asynchronous SSE monitoring.

### Phase 1: Submit KYC Data (REST)

**Endpoint:** `POST /v1/accounts`

The Sevino settings UI collects all required KYC fields:

- Legal name
- Date of birth
- SSN / tax ID
- Address
- Employment information
- Investor profile

This data is submitted as a single POST request. The user is never redirected to an Alpaca-hosted page.

**Agreement requirements:**

- Customer Agreement
- Margin Agreement (if applicable)
- For FDIC Sweep eligibility: account must be on Customer Agreement **revision 22.2024.08 or newer**
- Must present FDIC Bank Sweep Program Terms & Conditions during this flow

### Phase 2: Monitor Approval (SSE)

**Endpoint:** `GET /v1/events/accounts/status`

After submission, the account enters `SUBMITTED` status. The SSE connection receives status transitions:

| Transition | Meaning | Sevino Action |
|---|---|---|
| `SUBMITTED → APPROVAL_PENDING → APPROVED → ACTIVE` | Happy path — account is fully operational | Notify user, trigger FDIC Sweep enrollment |
| `SUBMITTED → ACTION_REQUIRED` | KYC check returned issues | SSE event includes `kyc_results` with field-level details. Surface in Settings UI. |
| `SUBMITTED → REJECTED` | Account denied | Display explanation and next steps |
| `SUBMISSION_FAILED` | Submission itself failed before KYC ran | Retry or surface error |

Full account status values: `INACTIVE`, `ONBOARDING`, `SUBMITTED`, `SUBMISSION_FAILED`, `ACTION_REQUIRED`, `ACCOUNT_UPDATED`, `APPROVAL_PENDING`, `APPROVED`, `REJECTED`, `ACTIVE`, `ACCOUNT_CLOSED`. See: https://docs.alpaca.markets/docs/accounts-statuses

### Authentication Flow (OAuth2 Client Credentials)

Alpaca supports OAuth2 Client Credentials for Broker API authentication. (HTTP Basic Auth is available as a legacy flow but OAuth2 is recommended for new integrations.)

1. Exchange `client_id` + `client_secret` for an access token:
   ```
   POST https://authx.sandbox.alpaca.markets/v1/oauth2/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=client_credentials&client_id=<ID>&client_secret=<SECRET>
   ```
2. Response: `{"access_token": "...", "expires_in": 899, "token_type": "Bearer"}`
3. Use `Authorization: Bearer <token>` for all subsequent API calls
4. Token expires in ~15 minutes — cache and refresh before expiry

**Important:** Alpaca only supports `client_secret_post` (credentials in form body). They do NOT support `client_secret_basic` (credentials in Authorization header).

Implementation: `app/services/alpaca_broker.py` — `AlpacaBrokerService` manages token caching and auto-refresh.

### Alpaca API Accepted Enum Values

> **CRITICAL:** Always verify field values against the official Alpaca API reference at
> https://docs.alpaca.markets/reference/createaccount before changing any mapping constants.
> Internal docs may contain outdated or incorrect values. The Alpaca API reference is the source of truth.

These are the exact values accepted by `POST /v1/accounts` as of April 2026:

| Field | Accepted Values |
|---|---|
| `investment_time_horizon` | `less_than_1_year`, `1_to_2_years`, `3_to_5_years`, `6_to_10_years`, `more_than_10_years` |
| `risk_tolerance` | `conservative`, `moderate`, `significant_risk` |
| `investment_objective` | `generate_income`, `preserve_wealth`, `market_speculation`, `growth`, `balance_preserve_wealth_with_growth` |
| `liquidity_needs` | `very_important`, `important`, `somewhat_important`, `does_not_matter` |
| `investment_experience_with_stocks` | `none`, `1_to_5_years`, `over_5_years` |
| `investment_experience_with_options` | `none`, `1_to_5_years`, `over_5_years` |
| `employment_status` | `unemployed`, `employed`, `student`, `retired` |
| `funding_source` (array) | `employment_income`, `investments`, `inheritance`, `business_income`, `savings`, `family` |
| `tax_id_type` | `USA_SSN`, `USA_ITIN`, and others (see API reference) |

> **Deprecation note:** Alpaca marks the investor profile fields (`investment_time_horizon`, `risk_tolerance`,
> `investment_objective`, `liquidity_needs`, `investment_experience_with_stocks`, `investment_experience_with_options`)
> as deprecated. They still work as of April 2026 but may be removed in a future API version. Monitor Alpaca's changelog.

### Sandbox vs. Production

- **Sandbox:** Account approval is fully automated with test fixtures.
- **Production:** Alpaca's operations team may perform manual review (approval SSE event could take longer). Show messaging: "Your account is being reviewed. We'll notify you when it's ready."

---

## Funding — ACH Transfers

**PRD References:** FR-3.3, FR-3.4, FR-3.5

### Bank Account Linking (Plaid)

Sevino uses **Plaid Link** on the mobile client to capture bank account info. Plaid generates a processor token passed to Alpaca.

**Endpoint:** `POST /v1/accounts/{account_id}/ach_relationships`

**Request body (Plaid path):** `{"processor_token": "<plaid_processor_token>"}` — the processor token alone is sufficient. Alpaca retrieves the bank and routing numbers directly from Plaid using the token. (The non-Plaid path requires `account_owner_name`, `bank_account_type`, `bank_account_number`, and `bank_routing_number` instead, and is not used by Sevino.)

**Response:** Returns a `relationship_id` — store this for subsequent transfers.

This is a one-time flow per bank account.

### Deposits and Withdrawals

**Endpoint:** `POST /v1/accounts/{account_id}/transfers`

**Request body:**

```json
{
  "transfer_type": "ach",
  "relationship_id": "<stored_relationship_id>",
  "amount": "500",
  "direction": "INCOMING",  // INCOMING = deposit, OUTGOING = withdrawal
  "timing": "immediate"
}
```

`timing` is required (`immediate` is the only currently supported value). `fee_payment_method` is optional (`"user"` | `"invoice"`, default `"invoice"`).

**Response:** Returns immediately with `status: QUEUED`.

**Transfer lifecycle (simplified):** `QUEUED → PENDING → COMPLETE` (or `REJECTED`)

Full transfer status values: `QUEUED`, `APPROVAL_PENDING`, `PENDING`, `SENT_TO_CLEARING`, `APPROVED`, `COMPLETE`, `REJECTED`, `CANCELED`, `RETURNED`. Handle `RETURNED` (ACH chargebacks) as a critical failure path — notify user and restrict future instant funding.

**Transfer record retention:** Transfer records are keyed by their own transfer `id`, not by `relationship_id`. Deleting an ACH relationship (`DELETE /v1/accounts/{id}/ach_relationships/{rel_id}`) marks it canceled but **does not delete the transfer history** — `GET /v1/accounts/{id}/transfers` still returns every transfer ever made, including those tied to since-deleted relationships. Our app mirrors this: never hard-delete `ach_relationships` or `plaid_items` rows; soft-delete via `status = 'CANCELED'` / `status = 'inactive'` so historical transfers can still be rendered with the correct bank nickname and mask. Full pattern in `docs/funding.md`.

**SSE Monitoring Endpoint:** `GET /v2/events/funding/status` (note: `/v1/events/transfers/status` is deprecated)

- ACH settlement: **1–3 business days**
- When SSE reports `COMPLETE`, push notification to user confirming funds are available
- **Sandbox:** Transfers simulate ACH delay with 10–30 minute processing time. Transfer then reflects via a cash deposit activity (`CSD`).

---

## Portfolio Data & Account Information

**PRD References:** FR-3.9, FR-4.3, FR-4.7, FR-9.1–FR-9.8

### Account Information

**Endpoint:** `GET /v1/trading/accounts/{account_id}/account`

**Returns:** Account object containing:

- `equity` — current total equity
- `last_equity` — previous close equity
- `cash` — available cash
- `buying_power` — available buying power
- Account status flags
- `cash_interest` object (within USD property) — FDIC Sweep interest data

**Used for:**

- Daily P/L calculation: `equity - last_equity`
- Status bar portfolio value and daily change indicator (FR-9.2)
- AI greeting: "Your portfolio is at $4,230, up 1.2% today" (FR-4.7)
- Cash balance and buying power display (FR-3.9)
- FDIC Sweep interest data (FR-3.12)

### Current Positions / Holdings

**Endpoint:** `GET /v1/trading/accounts/{account_id}/positions`

**Returns per position:**

- `symbol`, `qty`, `current_price`, `market_value`
- `cost_basis`, `unrealized_pl`, `unrealized_plpc`
- `lastday_price` (previous trading day's close, $)
- `change_today` (Alpaca's name; **percent factor of 1**, e.g. `"0.0084"` = 0.84%)

Market values are updated live by Alpaca — a fresh call returns current data.

> Note: Alpaca's `change_today` is a **percent factor**, not a dollar amount. Sevino's `/v1/portfolio/holdings` response renames this to `change_today_percent` and adds a separate `change_today` field that is the **position-level** `$` gain today (`(current_price − lastday_price) × qty`). Position-level matches the unit of `unrealized_pl`, so the iOS "Day's Gain" and "Total Gain" rows are directly comparable. When `lastday_price` is missing or zero (e.g. brand new listings), both fields zero out together — the response never pairs `$0.00` with a non-zero `%`.

**Used for:**

- Holdings modal from status bar (FR-9.6)
- Portfolio Summary Card — allocation breakdown, top holdings (FR-5.1)
- AI context injection for portfolio-related queries (FR-4.3)
- Concentration risk detection — flag if any single position exceeds 50% (FR-8.10)

### Portfolio History

**Endpoint:** `GET /v1/trading/accounts/{account_id}/account/portfolio/history`

**Returns:** Timeseries arrays of timestamps, equity values, and P/L data.

**Parameters:**

| Parameter | Options | Use Case |
|---|---|---|
| `period` | `1D`, `1W`, `1M`, `3M`, `6M`, `1A`, `all`, `intraday` | Time range for chart |
| `timeframe` | `1Min`, `5Min`, `15Min`, `1H`, `1D` | Resolution of data points |
| `date_start` / `date_end` | ISO 8601 dates | Custom date range |

**Automatic resolution defaults:**

- `1Min` for periods under 7 days
- `15Min` for under 30 days
- `1D` for longer periods

The v2 portfolio history engine updates in real-time for intraday timeframes.

**Powers:** Performance Chart Card (FR-5.1) with selectable time ranges (1D, 1W, 1M, 3M, 6M, 1Y, All).

### Order History

**Endpoint:** `GET /v1/trading/accounts/{account_id}/orders`

**Returns:** All orders with status, fill price, timestamps, order details.

**Filter param:** `status` = `open`, `closed`, `all`

**Powers:** Order History view in Settings > Accounts (FR-3.9).

### Account Activities

**Endpoint:** `GET /v1/accounts/activities`

**Returns:** Historical transaction activities:

- `FILL` — trade executions
- `DIV` — dividend payments
- `CSD` / `CSW` — ACH transfers (deposits/withdrawals)
- Other non-trade activities

Useful for building activity feeds and AI context ("what happened in my account this week?").

---

## Portfolio Read Endpoints (Sevino API)

The three Sevino-API routes the iOS portfolio surfaces depend on. Each one wraps an Alpaca call (or two) behind a Redis cache and a non-`ACTIVE` short-circuit. For the response field-by-field contract, ticket index, and decision history, see `.context/portfolio-data/architecture.md` and `.context/portfolio-data/tickets/README.md`.

### Routes

| Route | Used by (iOS) | Alpaca calls | Cache key | TTL |
|---|---|---|---|---|
| `GET /v1/portfolio/snapshot` | Status-bar pill, expanded modal hero | `GET /v1/trading/accounts/{id}/account` | `portfolio:snapshot:{user_id}` | 30s |
| `GET /v1/portfolio/holdings` | Holdings modal | `GET .../account` + `.../positions` (concurrent) | `portfolio:holdings:{user_id}` | 30s |
| `GET /v1/portfolio/history?range=1M` | Performance chart | `GET .../account/portfolio/history` | `portfolio:history:{user_id}:{range}` | 60s |

Routes are mounted in `app/main.py` under the `/v1/portfolio` prefix. Source: `app/routes/portfolio.py`, service `app/services/portfolio.py`.

### Decimal-as-string contract

All money / quantity / percentage fields serialize as JSON **strings**, not numbers. This avoids float drift across Python ↔ JSON ↔ Swift. The shared Pydantic aliases live in `app/schemas/_types.py`:

- `MoneyStr` — 2 decimal places, quantized (`"1084.92"`)
- `QtyStr` — up to 9 decimal places, fractional shares (`"0.125"`)
- `PctStr` — factor of 1, 4 decimal places (`"0.2731"` = 27.31%)

Every portfolio response model uses these aliases — never plain `Decimal`. iOS decodes via the `@DecimalString` property wrapper (`sevino-app/Sevino/Sevino/Utils/DecimalString.swift`).

### Caching

Redis client lives on `app.state.redis`, initialized in `app/lifecycle.py` from the same `redis_url` as ARQ. The cache helper in `app/cache.py`:

```python
async def cache_get_or_set(client: aioredis.Redis, key: str, ttl: int, fetcher: ...): ...
```

Caches the **serialized response dict**, not the raw Alpaca response — so transformations (decimal quantization, sorting, asset-name joins) are computed once per TTL window. Malformed cache entries fall back to the fetcher (see `#506`).

**Invalidation.** Transfer-status SSE events (`/v2/events/funding/status`, filtered to `entity_type == "Transfer"`) delete `portfolio:snapshot:{user_id}`, `portfolio:holdings:{user_id}`, and every `portfolio:history:{user_id}:{range}` key for the affected user so the iOS app sees fresh balances on the next read after a deposit/withdrawal. The 30–60s TTL is the safety net if the SSE connection drops and an event is missed. **Future:** wire SSE order fills the same way on each `fill` event.

> The v1 endpoint `/v1/events/transfers/status` is deprecated for new broker partners (returns HTTP 410). Sevino uses the v2 funding-status stream, which multiplexes Transfer/BankRelationship/WireBank events and exposes `event_id` as a ULID on the top-level field (resumed with `?since_id=<ulid>`).

**Do not add a background job that pre-warms these keys.** Refresh is pull-based from the iOS client.

### Non-`ACTIVE` gate (at the dependency, not the service)

The portfolio surfaces are gated **before** the service runs, by the FastAPI dependency `get_alpaca_account_context` in `app/dependencies/portfolio.py`. If the caller has no `brokerage_accounts` row, or their `account_status != "ACTIVE"`, the dependency raises:

```python
raise ConflictError(
    "Your brokerage account is not active yet.",
    code="ACCOUNT_NOT_ACTIVE",
    detail={"account_status": status},
)
```

This maps to **409 `ACCOUNT_NOT_ACTIVE`** with `detail.account_status` set to the actual Alpaca status string (e.g. `"APPROVAL_PENDING"`, `"ACTION_REQUIRED"`, `"REJECTED"`, or `null` if no row exists). iOS reads `detail.account_status` from the 409 response and renders the corresponding empty-state copy ("Being reviewed", "Action required", "Rejected") instead of a misleading `$0.00`.

Because the dependency 409s before the service runs, `PortfolioService` itself trusts that `ctx.account_status == "ACTIVE"` on entry — there are no defensive `if ctx.account_status != "ACTIVE": ...` branches inside the service. **Don't add them**; that path is unreachable.

Rationale for gating in the dependency rather than calling Alpaca: the broker's behavior for non-`ACTIVE` accounts on the `account` / `positions` / `portfolio/history` endpoints is undocumented (200 with empty data? 4xx?). Cheaper and safer to skip the round trip and centralize the check at one boundary.

### `range` → Alpaca params mapping (`/v1/portfolio/history`)

Query parameter `range` is the iOS-facing enum; the service maps it to Alpaca's `period` / `timeframe` / `start`. Anything outside this set returns 422.

| iOS `range` | Alpaca `period` | Alpaca `timeframe` | Alpaca `start` | Alpaca `end` |
|---|---|---|---|---|
| `1D` | `1D` | `5Min` | — | — |
| `1W` | `1W` | `1H` | — | — |
| `1M` | `1M` | `1D` | — | — |
| `3M` | `3M` | `1D` | — | — |
| `6M` | `6M` | `1D` | — | — |
| `YTD` | (omit) | `1D` | `YYYY-01-01T00:00:00Z` (computed) | `now` (computed) |
| `1Y` | `1A` | `1D` | — | — |
| `ALL` | `all` | `1W` | — | — |

YTD must pass an explicit `end` — when only `start` is sent, Alpaca silently caps the response at ~1 month from `start`, which produces an empty chart for accounts opened any time mid-year. All other ranges use `period`, which defines the window from now backwards and doesn't have this issue.

Source of truth: `range_to_alpaca_params()` in `app/services/portfolio.py`.

### Errors

Domain exceptions bubble up to the registered handlers in `app/exceptions.py`:

| Raised | HTTP | Code | Notes |
|---|---|---|---|
| `ConflictError("ACCOUNT_NOT_ACTIVE")` | 409 | `ACCOUNT_NOT_ACTIVE` | most common — raised by `get_alpaca_account_context` for non-`ACTIVE` users; `detail.account_status` carries the Alpaca status |
| `AlpacaBrokerError` (4xx) | 422 | `ALPACA_ERROR` | input rejected by broker |
| `AlpacaBrokerError` (5xx) | 502 | `ALPACA_ERROR` | broker outage — distinct status from input errors |
| `AlpacaBrokerUnavailableError` | 503 | `ALPACA_UNAVAILABLE` | sets `Retry-After: 30` |

Routes never `try/except` — handlers map exceptions to the structured `error_response()` shape.

### Sandbox quirks (broker-api.sandbox.alpaca.markets)

Alpaca's broker sandbox is *approximately* the same as production but has documented and observed inconsistencies. None of these reproduce in production; do not add fallbacks for them.

| Quirk | What you'll see | Why |
|---|---|---|
| `last_equity = 0` on `GET /v1/trading/accounts/{id}/account` | iOS card shows `+$<full_equity> (+0.00%) today` for 1D — giant dollar amount, 0% — even when daily history clearly has yesterday's close | Sandbox skips the nightly EOD job that writes `last_equity` onto the trading-account record. The portfolio-history pipeline runs (so daily bars are present), but the snapshot pipeline doesn't see the previous close. |
| `account_funded_at = null` despite real equity + open positions | Same account can have `equity = $50K`, real positions, and `account_funded_at = null` | Same root cause — separate ledger pipeline that doesn't run in sandbox. |
| Sub-dollar drift between live `equity` and the last 5-min portfolio-history bar at close | `account.equity` ≠ history's last bar by a few cents, *frozen post-close* | Documented Alpaca pricing rule: bars use last-trade between 04:00–22:00 ET, then re-stamp to official close after 22:00 ET. Sandbox synthetic feeds for last-trade vs official-close don't reconcile. Industry-normal drift; even Robinhood/IBKR have it. |
| `current_price` on positions equals `lastday_price` even after intraday history clearly moved | iOS holdings modal shows `change_today = $0.00` while the 1D chart shows real movement | Sandbox's position-pricing pipeline is a separate simulator from the portfolio-history pipeline. |

For the smoke-test test user (`+15551234567` linked via `scripts/seed_portfolio_e2e.py`), the 1D card will always look weird because `last_equity = 0`. Use the 1M+ ranges to validate the gain UX; production accounts will look correct on 1D.

Sources:
- [Alpaca: Portfolio History reference](https://docs.alpaca.markets/reference/getaccountportfoliohistory-1)
- [Alpaca blog: portfolio-history pricing rules](https://alpaca.markets/learn/introducing-the-new-portfolio-history-endpoint-at-alpaca)
- [Forum: Historic P/L data does not match current Equity](https://forum.alpaca.markets/t/historic-p-l-data-does-not-match-current-equity/2394)
- [Forum: Inconsistent equity data from get_portfolio_history](https://forum.alpaca.markets/t/inconsistent-equity-data-from-tradingclient-get-portfolio-history/18644)

---

## Status Bar & Modal Data Architecture

**PRD References:** FR-9.1–FR-9.8

Sevino's UI is chat-first. All detailed financial data lives behind modals opened explicitly by the user. Market data is fetched on demand.

### On-Demand Fetch Pattern

User taps a button → app calls Alpaca REST API → renders result with brief loading indicator.

**Caching strategy:**

- **Backend:** Redis cache, 30–60 second TTL per user per endpoint
- **Frontend:** In-memory cache so navigation back to a previously viewed modal feels instant while fresh data loads in background

| User Action | Alpaca Endpoint(s) | Data Returned |
|---|---|---|
| Opens app / starts new conversation | `GET .../account` | Equity, cash, daily change for status bar + AI greeting |
| Force-presses portfolio value | `GET .../account` + `.../account/portfolio/history` | Total value, daily change, performance chart data |
| Taps Holdings icon | `GET .../positions` | All open positions with current market values, P/L |
| Taps Radar icon | `GET /v2/stocks/snapshots?symbols=X,Y,Z` | Current prices for all Radar items (batch call) |
| Asks AI about a stock | `GET /v2/stocks/{symbol}/snapshot` + `/bars` | Price, daily change, sparkline data for Stock Info Card |
| Asks AI about portfolio | `GET .../account` + `.../positions` + `.../portfolio/history` | Full portfolio context for AI response |
| Taps a stock's chart time range | `GET /v2/stocks/{symbol}/bars?timeframe=X` | Historical bars for selected period |

### Status Bar Background Refresh

The status bar showing portfolio value is the one always-visible element.

**Refresh mechanism:** Frontend background job calls account endpoint **every 5 minutes**.

**Endpoint:** `GET /v1/trading/accounts/{account_id}/account`

- Returns `equity`, `last_equity`, `cash`
- Frontend computes daily change: `equity - last_equity`
- Between refreshes, the number is static
- **Frontend-initiated** — only runs while app is active and in foreground (not a server-side polling loop)

### Force-Press Modal Data Sources

When the user force-presses the portfolio value (FR-9.4):

| Modal Element | Alpaca Endpoint |
|---|---|
| Total portfolio value, daily change ($/%) | `GET /v1/trading/accounts/{id}/account` |
| Performance chart with time ranges | `GET /v1/trading/accounts/{id}/account/portfolio/history` |
| Holdings breakdown | `GET /v1/trading/accounts/{id}/positions` |
| Cash balance, buying power | `GET /v1/trading/accounts/{id}/account` (same call) |

All on-demand REST calls triggered when modal opens.

---

## Order Execution & Trade Flow

**PRD References:** FR-8.1–FR-8.15

### Placing Orders (REST)

**Endpoint:** `POST /v1/trading/accounts/{account_id}/orders`

When the user confirms a trade via long-press on the Trade Confirmation Card (FR-8.4), the backend submits the order.

#### Market Order (Dollar Amount — Fractional)

```json
{
  "symbol": "TSLA",
  "notional": "200",
  "side": "buy",
  "type": "market",
  "time_in_force": "day"
}
```

- The `notional` field enables **dollar-amount purchases** resulting in fractional shares (FR-3.6, FR-8.8)
- **Minimum** market value for buy orders: **$1.00**
- `notional` supports up to **2 decimal places**

#### Limit Order

```json
{
  "symbol": "AAPL",
  "qty": "10",
  "side": "buy",
  "type": "limit",
  "limit_price": "180.00",
  "time_in_force": "gtc"
}
```

- Limit orders (FR-8.7) use `qty` instead of `notional`
- `time_in_force`: `day` (expires at market close) or `gtc` (good 'til canceled)

#### After-Hours Queuing

When markets are closed (FR-8.15):

- Orders submitted with `time_in_force: day` will queue and execute at next market open
- **Must display clear warnings** about potential price differences
- Use `GET /v1/clock` — returns `is_open`, `next_open`, `next_close` timestamps

### Order Status Updates (SSE)

**Endpoint:** `GET /v2/events/trades` (SSE)

After placing an order, the trade events SSE listener processes `trade_updates` events and updates the `order_events` row:

| Event | Meaning | Sevino Action |
|---|---|---|
| `new` | Order routed to exchange | Update order status in UI |
| `fill` | Order completely filled (includes `fill_price`, `qty`, `position_qty`) | Render Trade Confirmation Card success state (FR-8.12) |
| `partial_fill` | Some shares filled, more pending | Update card with partial fill details |
| `canceled` | Order was canceled | Notify user |
| `rejected` | Order rejected by exchange or Alpaca | Render error state on Trade Confirmation Card (FR-8.13) |
| `pending_new` | Order received but not yet accepted | Show pending indicator |
| `replaced` | Order was replaced with new parameters | Update card with new details |

**Note:** Most market orders during market hours fill instantly — `fill` event typically arrives within milliseconds. Limit orders may remain open indefinitely.

---

## High-Yield Cash — FDIC Bank Sweep

**PRD References:** FR-3.10–FR-3.15

Alpaca's cash management program: uninvested USD cash earns interest while remaining fully liquid as buying power. **Revenue stream for Sevino** via partner take rate.

### APR Tier Configuration

APR Tiers are configured server-side by Alpaca during partner onboarding. Each tier defines:

- `account_rate_bps` — interest rate the customer earns (e.g., 320 bps = 3.20% APY)
- `correspondent_fee_bps` — Sevino's partner take rate (e.g., 10 bps = 0.10% APR)

Updates to a tier apply to **all accounts** assigned to it. Self-service API tier creation is planned for a future Alpaca release; currently managed by Alpaca's team.

### Enrollment Flow

Auto-enroll upon account creation (FR-3.10):

1. User completes account creation, signs Customer Agreement (revision ≥ 22.2024.08), is presented FDIC Bank Sweep Terms & Conditions.
2. Backend monitors account status SSE stream for `ACTIVE` transition.
3. Upon `ACTIVE`, backend enrolls by assigning APR Tier:

**Endpoint:** `PATCH /v1/accounts/{account_id}`

**Body:** Assign account to Sevino's preconfigured APR Tier ID.

4. Eligible settled cash begins sweeping once daily (cutoff ~11:45 AM ET). Swept cash earns interest and remains available as buying power.

### Reading Interest Data

The account object includes a `cash_interest` object within the `USD` property containing:

- Current APR tier assignment
- Interest details

**Endpoint:** `GET /v1/trading/accounts/{account_id}/account` (same account endpoint used elsewhere)

Additionally, an EOD Cash Interest Details endpoint updates daily. Interest is booked on the last business day of each month and compounds automatically.

### FDIC Insurance Coverage

- Swept cash is FDIC pass-through insured up to **$1,000,000 per customer** (based on number of participating program banks, each providing up to $250,000). Note: verify current limits at https://docs.alpaca.markets/docs/fdic-sweep-program
- Funds **in the brokerage account**: SIPC-insured (up to $500K, $250K cash sub-limit) but **NOT FDIC-insured**
- Funds **swept to program banks**: intended to be FDIC-insured but **NOT SIPC-protected**
- Coverage is "potentially eligible" and subject to conditions
- Interest rate is variable, tied to federal funds rate (FR-3.15) — display with disclaimer

---

## Market Data Integration

**PRD References:** FR-5.1, FR-6.2–FR-6.8, FR-7.1–FR-7.10

### REST Market Data Endpoints

> **Base URL note:** Market data endpoints use a **different base URL** from the Broker API:
> - Production: `https://data.alpaca.markets`
> - Sandbox: `https://data.sandbox.alpaca.markets`
>
> The `/v2/stocks/...` paths below are relative to this base URL, not `broker-api.alpaca.markets`.

| Endpoint | Returns | Use Case |
|---|---|---|
| `GET /v2/stocks/{symbol}/snapshot` | Latest trade, quote, minute bar, daily bar, prev daily bar | Stock Info Card — single call for current price, daily change, key data |
| `GET /v2/stocks/snapshots?symbols=X,Y` | Multi-symbol snapshots | Comparison analysis, Radar Card pricing, batch quote fetches |
| `GET /v2/stocks/{symbol}/bars` | Historical OHLCV bars (configurable timeframe) | Sparkline charts, Performance Chart Cards |
| `GET /v2/stocks/{symbol}/trades/latest` | Most recent trade for a symbol | Latest price when snapshot not needed |
| `GET /v2/stocks/{symbol}/quotes/latest` | Most recent quote (bid/ask) | Spread information for advanced users |

The **snapshot endpoint is the most efficient** single call for Stock Info Cards — bundles current price, daily change, and previous close in one response.

### Historical Bars for Charts — Time Range Mapping

| UI Time Range | Bars `timeframe` | `start` | Notes |
|---|---|---|---|
| 1D | `5Min` | Market open today | Intraday chart, ~78 data points |
| 1W | `15Min` | 5 trading days ago | Weekly detail |
| 1M | `1Hour` | 1 month ago | Monthly overview |
| 3M | `1Day` | 3 months ago | Daily bars |
| 6M | `1Day` | 6 months ago | Daily bars |
| 1Y | `1Day` | 1 year ago | Daily bars |
| All | `1Week` or `1Month` | Earliest available | Long-term trend, coarser resolution |

### Real-Time Market Data Stream (Deferred — Future Option)

**Endpoint:** `wss://stream.data.alpaca.markets/v2/{feed}`

Not needed for current chat-first architecture where all data is behind user-initiated modals. Available if a future feature (e.g., live trading screen) requires continuous price streaming.

### Market Data Authentication (Broker API Partners)

Broker API partners use the **Client Credentials flow**:

1. Exchange credentials for a short-lived access token (valid **15 minutes**)
2. Use that token to authenticate REST API requests

---

## AI Agent — Alpaca Data in Context

**PRD References:** FR-4.1–FR-4.8, FR-5.1–FR-5.3

Every AI response involving financial data **must be grounded in real Alpaca API data** retrieved via tool calls — never generated from training data (FR-4.8).

### Context Injection on Conversation Start

When a new conversation opens, the backend **pre-fetches** and injects into Claude's system prompt:

| Data | Alpaca Endpoint | Purpose |
|---|---|---|
| Account summary (equity, cash, buying power, daily change) | `GET /v1/trading/.../account` | Greeting message (FR-4.7), general awareness |
| Current positions (symbol, qty, market value, P/L) | `GET /v1/trading/.../positions` | Portfolio context for any question |
| Account status (active, restricted, etc.) | `GET /v1/accounts/{id}` | Determines if trading is available |
| FDIC Sweep interest data | Same account endpoint (`cash_interest`) | Interest rate references (FR-3.13) |

This enables the static greeting without a tool call on first message.

### Tool Calls for On-Demand Data

When the user asks a question requiring fresh/specific data, the AI invokes tool calls that trigger Alpaca API requests from the backend:

| User Query | Tool Call | Alpaca Endpoint(s) | UI Card |
|---|---|---|---|
| "Tell me about AAPL" | `get_stock_info(AAPL)` | `GET /v2/stocks/AAPL/snapshot` + `bars` | Stock Info Card |
| "How's my portfolio doing?" | `get_portfolio_summary()` | `account` + `positions` + `portfolio/history` | Portfolio Summary Card |
| "Buy $200 of TSLA" | `preview_trade({...})` | `GET /v2/stocks/TSLA/quotes/latest` | Trade Confirmation Card |
| "Show me TSLA's chart" | `get_stock_chart(TSLA, 1M)` | `GET /v2/stocks/TSLA/bars?timeframe=1Day` | Performance Chart Card |
| "How much interest am I earning?" | `get_account_info()` | `GET /v1/trading/.../account` | Text response with rate data |

**Internet kill switch (FR-4.9):** When toggled off, disables tool calls. AI can still respond using training knowledge for general financial education but cannot retrieve real-time data or execute trades. Status bar continues updating independently.

---

## AI Radar Data Flow

**PRD References:** FR-7.1–FR-7.10

### Radar Generation (Daily Background Job)

The daily backend job (FR-7.2):

1. Retrieves user's Profile Card (goals, risk tolerance, time horizon, experience level)
2. Fetches current market data via Alpaca REST (snapshots, daily bars for momentum/trend signals)
3. Fetches user's current positions (diversification opportunities)
4. Runs selection algorithm (profile alignment, risk match, sector relevance, market conditions)
5. Generates context blurb per item via Claude — **educational/informational only** (FR-7.9)

**Storage:** Radar items stored in **Sevino's database** (not Alpaca Watchlists) because they carry metadata Alpaca doesn't support: AI-generated blurb, 7-day expiry timer (FR-7.6), favorited flag (FR-7.7), profile-alignment reasoning.

### Radar Data Flow on Modal Open

Sevino's DB stores only **ticker symbols + AI metadata** (blurbs, expiry dates, favorited flags). **No price data is stored.**

When user taps Radar icon (FR-7.4):

**Endpoint:** `GET /v2/stocks/snapshots?symbols=VTI,AAPL,MSFT,...`

Returns latest trade, quote, daily bar, prev daily bar for each symbol in one response. Backend merges price data with stored metadata and returns combined result. **Cached 30–60 seconds.**

### Favorited Items / Watchlist

Favorited Radar items (FR-7.7) persist in **Sevino's database**. Alpaca has a Watchlists API (`POST /v1/trading/accounts/{id}/watchlists`) but Sevino's own storage is preferred because favorites are tied to the Radar system and include unsupported metadata.

---

## Contextual Shortcuts — Market Awareness

**PRD References:** FR-10.1–FR-10.6

### Alpaca Data for Shortcut Logic

| Shortcut Condition | Alpaca Data Source | Protocol |
|---|---|---|
| Pre-market / market hours / post-market | `GET /v1/clock` (`is_open`, `next_open`, `next_close`) | REST |
| Market drop >2% | `GET /v2/stocks/SPY/snapshot` (checked on app open + during 5-min status bar refresh) | REST |
| Post-earnings for held stocks | Account activities or external earnings calendar | REST + external |
| User holds specific stocks | `GET /v1/trading/.../positions` | REST |

The market clock endpoint is lightweight — call on app open or new conversation start.

For "after >2% drop": check SPY's daily change during the status bar's 5-minute background refresh and flag when threshold is breached.

---

## Asset Lookup & Eligibility

**PRD References:** FR-3.6, FR-3.7, FR-8.8, FR-8.9

**Endpoint:** `GET /v1/assets` or `GET /v1/assets/{symbol}`

**Returns:**

- `symbol`, `name`, `exchange`, `status` (active/inactive)
- `tradable` — whether the asset can be traded
- `fractionable` — whether fractional trading is supported
- `class` — asset class

**Used for:**

- **Symbol disambiguation** (FR-8.9): "Did you mean Apple Inc (AAPL) or Apple Hospitality REIT (APLE)?"
- **Fractional share eligibility** (FR-8.8): check `fractionable` field
- **Asset class filtering** (FR-3.7): Sevino only supports `us_equity` class — no crypto or options

---

## Error Handling & Edge Cases

### API Error Responses

| Status | Meaning | Sevino Handling |
|---|---|---|
| `400` | Bad request (invalid parameters) | Parse error message, surface to user via AI or UI |
| `403` | Auth failed or account restricted | Check API key validity; check `trading_blocked` flag |
| `404` | Resource not found (symbol, account, order) | Clear message: "I couldn't find that symbol" |
| `422` | Unprocessable (insufficient funds, order < $1) | Surface specific reason: "You don't have enough buying power" |
| `429` | Rate limit exceeded | Implement exponential backoff; queue and retry |
| `500` | Server error | Retry with backoff; if persistent, surface error to user |

### SSE Connection Management

- Track last received `event_ulid` (or `event_id` on v2-migrated endpoints — both are ULIDs)
- On reconnection, use `since_ulid` / `since_id` parameter to replay missed events
- Implement exponential backoff for reconnection attempts
- Handlers are UPDATE-idempotent, so replay after reconnect is safe — no explicit dedup keys needed
- Stay within Alpaca's **25 concurrent connections per API key** limit across all environments sharing the sandbox key

### PDT (Pattern Day Trader) Considerations

If a user's account gets flagged as a Pattern Day Trader:

- Account may face **trading restrictions if equity falls below $25,000**
- **FDIC Sweep enrollment is automatically revoked** (account unenrolled, swept balances return to brokerage account)
- AI should detect and explain this if user asks about account status or missing interest

---

## Complete Endpoint Reference

### Account Management

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/accounts` | `POST` | Create new brokerage account (KYC submission) |
| `/v1/accounts/{id}` | `GET` | Retrieve account details and status |
| `/v1/accounts/{id}` | `PATCH` | Update account (assign APR Tier for FDIC Sweep) |
| `/v1/accounts/activities` | `GET` | Historical transaction activities (fills, dividends, etc.) |
| `/v1/events/accounts/status` | `GET` (SSE) | Stream account status change events |

### Funding & Transfers

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/accounts/{id}/ach_relationships` | `POST` | Create ACH relationship via Plaid processor token |
| `/v1/accounts/{id}/ach_relationships` | `GET` | List existing ACH relationships |
| `/v1/accounts/{id}/ach_relationships/{rel_id}` | `DELETE` | Unlink (cancel) an ACH relationship. Transfer history is retained. |
| `/v1/accounts/{id}/transfers` | `POST` | Initiate ACH deposit or withdrawal |
| `/v1/accounts/{id}/transfers` | `GET` | List transfers and their statuses |
| `/v2/events/funding/status` | `GET` (SSE) | Stream transfer status change events. Note: `/v1/events/transfers/status` is deprecated. |

### Trading

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/trading/accounts/{id}/orders` | `POST` | Place a new order |
| `/v1/trading/accounts/{id}/orders` | `GET` | List orders (open, closed, or all) |
| `/v1/trading/accounts/{id}/orders/{order_id}` | `GET` | Get specific order details |
| `/v1/trading/accounts/{id}/orders/{order_id}` | `PATCH` | Replace/modify an open order |
| `/v1/trading/accounts/{id}/orders/{order_id}` | `DELETE` | Cancel an open order |
| `/v1/trading/accounts/{id}/account` | `GET` | Account info (equity, cash, buying power, interest) |
| `/v1/trading/accounts/{id}/positions` | `GET` | List all open positions |
| `/v1/trading/accounts/{id}/positions/{symbol}` | `GET` | Get position for specific symbol |
| `/v1/trading/accounts/{id}/account/portfolio/history` | `GET` | Portfolio history timeseries |
| `/v2/events/trades` | `GET` (SSE) | Stream order status change events (fills, cancels, rejects). Note: `/v1/events/trades` is deprecated for new partners. |

### Market Data

| Endpoint | Method | Purpose |
|---|---|---|
| `/v2/stocks/{symbol}/snapshot` | `GET` | Latest trade, quote, bar, daily data for a symbol |
| `/v2/stocks/snapshots?symbols=X,Y` | `GET` | Batch snapshots for multiple symbols |
| `/v2/stocks/{symbol}/bars` | `GET` | Historical OHLCV bars (configurable timeframe) |
| `/v2/stocks/{symbol}/trades/latest` | `GET` | Most recent trade for a symbol |
| `/v2/stocks/{symbol}/quotes/latest` | `GET` | Most recent quote for a symbol |
| `/v1/assets` | `GET` | List all tradable assets |
| `/v1/assets/{symbol}` | `GET` | Asset details (fractionable, tradable, etc.) |
| `/v1/clock` | `GET` | Market clock (is_open, next_open, next_close) |
| `/v1/calendar` | `GET` | Market calendar (trading days) |
| `wss://stream.data.alpaca.markets/v2/{feed}` | WebSocket | Real-time quotes, trades, bars stream (future option) |

### Watchlists (Alpaca-native, optional — Sevino uses own DB instead)

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/trading/accounts/{id}/watchlists` | `POST` | Create a watchlist |
| `/v1/trading/accounts/{id}/watchlists` | `GET` | List all watchlists |
| `/v1/trading/accounts/{id}/watchlists/{wl_id}` | `PUT` | Update watchlist |
| `/v1/trading/accounts/{id}/watchlists/{wl_id}` | `DELETE` | Delete watchlist |

> **Note:** Sevino stores Radar and favorite data in its own database rather than Alpaca's Watchlists API because the Radar system requires metadata (AI blurbs, expiry timers, profile alignment) that Alpaca's schema does not support.

---

## Future Enhancements

### Real-Time Market Data WebSocket

**Endpoint:** `wss://stream.data.alpaca.markets/v2/{feed}`

Replace on-demand REST for price data if a future feature requires continuously updating prices. Would involve managing persistent connections, symbol subscriptions across users, and a fan-out layer to push updates to individual mobile sessions.

---

## Implementation Quick Reference

### Caching Strategy

| Layer | TTL | Scope |
|---|---|---|
| Backend Redis | 30–60 seconds | Per user per endpoint |
| Frontend in-memory | Until next navigation or explicit refresh | Per modal/screen |

### Background Jobs

| Job | Frequency | What It Does |
|---|---|---|
| Status bar refresh | Every 5 minutes (frontend, foreground only) | Calls account endpoint, updates equity display |
| AI Radar generation | Daily | Generates personalized stock recommendations |
| SSE listeners | Persistent connections | Receive account status, transfer status, and trade events |

### Rate Limit Protection

- All Alpaca REST calls go through backend Redis cache (30–60s TTL)
- On `429` response: exponential backoff with retry
- Frontend in-memory cache prevents duplicate requests on rapid navigation
