# Sevino Database Schema

**MVP / Closed Beta — v2.1 | March 2026**

| | |
|---|---|
| **Database** | PostgreSQL via Supabase |
| **Tables** | 20 |
| **Views** | 1 (`activity_feed`) |
| **Platform** | iOS (Swift) + FastAPI |
| **Brokerage** | Alpaca Securities LLC |
| **AI Provider** | Claude (Anthropic) |

---

## 1. Overview

This document describes the database schema for Sevino's MVP/closed beta release. The schema supports user onboarding, Alpaca brokerage integration, AI-powered chat with tool calling, trade execution, watchlists, and regulatory compliance.

The database runs on PostgreSQL managed by Supabase. Authentication is handled by Supabase Auth, which provides the `auth.users` table automatically. All user-scoped tables reference `auth.users(id)` via a `user_id` foreign key.

### 1.1 Design Principles

- **Accounts abstraction layer:** A generic `accounts` table sits between users and all financial data. At MVP only Alpaca accounts exist, but the structure supports Plaid-connected brokerages post-MVP without foreign key migrations.
- **Live API over local sync:** Portfolio data (positions, balances, portfolio history) is fetched live from Alpaca's API rather than synced into local tables.
- **Local records for audit trail:** Orders and transfers are stored locally because they link to AI conversations for the audit trail, and trade execution logs must be retained for regulatory compliance.
- **AI observability built in:** Prompt versioning, response metadata (latency, stop reason, errors), tool call logging, and user feedback are all captured to support debugging and continuous improvement.
- **Row Level Security:** Every user-scoped table has Supabase RLS enabled, ensuring users can only access their own data.

### 1.2 What Lives in the Database vs. APIs

| Data | Source | Stored Locally? |
|---|---|---|
| Account existence & status | Alpaca SSE events | Yes (`alpaca_accounts`) |
| Cash balance, buying power | Alpaca API live | No |
| Positions / holdings | Alpaca API live | No |
| Portfolio history (charts) | Alpaca API live | No |
| Order records | Created locally + SSE | Yes (`orders`) |
| Transfer records | Created locally + SSE | Yes (`transfers`) |
| Security reference data | Cached from Alpaca/Polygon | Yes (`securities`) |

### 1.3 Table Summary by Domain

| Domain | Tables | Purpose |
|---|---|---|
| Users & Onboarding | `user_profiles`, `user_preferences`, `disclaimer_acceptances` | Onboarding data, app settings, legal tracking |
| Accounts | `accounts`, `alpaca_accounts`, `bank_links` | Brokerage accounts and bank linking |
| Reference Data | `securities` | Ticker/price cache for display |
| Trading | `orders`, `transfers` | Order and deposit/withdrawal lifecycle |
| AI Conversations | `conversations`, `messages`, `tool_calls`, `message_feedback` | Chat persistence, debugging, quality tracking |
| Audit Trail | `trade_audit_logs` | Regulatory compliance for trade execution |
| Watchlists | `watchlists`, `watchlist_items` | User-curated security lists |
| Regulatory Docs | `documents` | Alpaca-generated statements and tax forms |
| Config & Events | `feature_flags`, `user_feature_flags`, `webhook_events` | Beta rollout control and webhook processing |

---

## 2. Users & Onboarding

Authentication is handled entirely by Supabase Auth. When a user registers via email/password, Apple Sign-In, or Google Sign-In, Supabase creates a row in `auth.users` with a UUID primary key. Every user-scoped table references `auth.users(id)` via `user_id` with `ON DELETE CASCADE`.

### 2.1 `user_profiles`

Stores onboarding questionnaire answers collected during first login (FR-2.1). Injected into every AI conversation as context for personalized responses (FR-2.5). One row per user (`UNIQUE` on `user_id`).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. UNIQUE. |
| `age` | INT | User's age |
| `annual_income` | INT | Annual income in dollars |
| `net_worth` | INT | Total net worth in dollars |
| `risk_tolerance` | TEXT | `conservative`, `moderate`, `aggressive` |
| `investment_goals` | TEXT[] | Array: `retirement`, `house_down_payment`, `wealth_building`, `education`, `other` |
| `time_horizon` | TEXT | `1-3_years`, `3-10_years`, `10+_years` |
| `experience_level` | TEXT | `beginner`, `intermediate`, `advanced` |
| `onboarding_completed` | BOOL | Whether the user has finished onboarding |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 2.2 `user_preferences`

App-level settings separate from financial profile data. One row per user.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. UNIQUE. |
| `theme` | TEXT | UI theme. Default: `system` |
| `default_order_type` | TEXT | `market` or `limit`. Default: `market` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 2.3 `disclaimer_acceptances`

Immutable, append-only legal audit log. Rows are never updated or deleted. Unique constraint on `(user_id, type, version)` ensures each version is accepted exactly once.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)` |
| `disclaimer_type` | TEXT | `tos`, `privacy_policy`, `risk_disclosure`, `sipc_info` |
| `disclaimer_version` | TEXT | Version string (e.g., `1.0`, `2.0`) |
| `accepted_at` | TIMESTAMPTZ | When the user accepted. Default: `now()` |
| `ip_address` | TEXT | IP at time of acceptance |

---

## 3. Accounts

A generic `accounts` table serves as the envelope that all downstream tables reference. Post-MVP, Plaid-connected brokerage accounts will be added by creating rows with `account_type = 'plaid'` — no existing foreign keys need to change.

### 3.1 `accounts`

Source-agnostic account envelope. Portfolio data (balances, positions) is fetched live from Alpaca at runtime.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Universal account identifier |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. Not unique (multiple accounts allowed). |
| `account_type` | TEXT | `alpaca` or `plaid` |
| `account_subtype` | TEXT | `individual`, `roth_ira`, `traditional_ira`, `sep_ira`, `hsa`, `401k`. Default: `individual` |
| `display_name` | TEXT | User-facing label. Default: `AI Trading Account` |
| `institution_name` | TEXT | Brokerage name. `Alpaca` at MVP. |
| `account_mask` | TEXT | Last 4 digits (e.g., `••••4821`) |
| `is_active` | BOOL | Soft-delete flag |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 3.2 `alpaca_accounts`

Alpaca-specific detail table. One-to-one with an `accounts` row where `account_type = 'alpaca'`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `account_id` **[FK]** | UUID | FK → `accounts(id)`. UNIQUE (1:1). |
| `alpaca_account_id` | TEXT | Alpaca's account UUID. UNIQUE. |
| `kyc_status` | TEXT | `pending`, `submitted`, `approved`, `rejected`, `action_required` |
| `account_status` | TEXT | `pending`, `active`, `disabled`, `closed` |
| `account_number` | TEXT | Alpaca account number |
| `currency` | TEXT | Default: `USD` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 3.3 `bank_links`

Bank accounts linked for ACH deposits/withdrawals (FR-4.9). FKs to `alpaca_accounts` because ACH funding is Alpaca-specific. One-to-many.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. For RLS. |
| `alpaca_account_id` **[FK]** | UUID | FK → `alpaca_accounts(id)` |
| `alpaca_ach_relationship_id` | TEXT | Alpaca's ACH relationship ID |
| `plaid_institution_id` | TEXT | Plaid's institution ID (for bank logos) |
| `bank_name` | TEXT | Human-readable bank name |
| `account_mask` | TEXT | Last 4 digits of bank account |
| `account_type` | TEXT | `checking` or `savings` |
| `status` | TEXT | `queued`, `approved`, `canceled` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

> **Future: Plaid Brokerage Aggregation** — Post-MVP, `plaid_items` and `plaid_connections` tables will be added. Commented-out SQL is ready in the schema file. All downstream tables already reference `accounts(id)`, so no FK migrations are required.

---

## 4. Reference Data

### 4.1 `securities`

Master reference catalog of tradeable instruments. Shared across all users (no `user_id`), read-only for authenticated users via RLS. Cached price data is refreshed on a schedule from Alpaca/Polygon.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `ticker_symbol` | TEXT | Stock ticker (e.g., `AAPL`). UNIQUE. |
| `name` | TEXT | Full company/fund name |
| `asset_type` | TEXT | `equity` or `etf` |
| `exchange` | TEXT | Trading exchange (NYSE, NASDAQ, etc.) |
| `is_tradable` | BOOL | Whether the security can currently be traded |
| `cached_price` | NUMERIC(14,4) | Current market price (refreshed on schedule) |
| `cached_price_change` | NUMERIC(14,4) | Absolute dollar change for the day |
| `cached_price_change_pct` | NUMERIC(8,4) | Percentage change for the day |
| `cache_updated_at` | TIMESTAMPTZ | When the price cache was last refreshed |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 5. Trading

Orders and transfers are stored locally for the audit trail, AI conversation linkage, and regulatory compliance (3-year retention). The backend creates a row when submitting to Alpaca and updates it via SSE events.

### 5.1 `orders`

Every trade placed through Alpaca. Supports market/limit orders (FR-10.6), fractional shares via notional amounts (FR-10.7), order queuing outside market hours (FR-10.8), and replacement chains via self-referential FKs.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Sevino's internal order ID |
| `account_id` **[FK]** | UUID | FK → `accounts(id)` |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. For RLS. |
| `security_id` **[FK]** | UUID | FK → `securities(id)` |
| `alpaca_order_id` | TEXT | Alpaca's order UUID. UNIQUE. |
| `client_order_id` | TEXT | Idempotency key. UNIQUE. |
| `ticker_symbol` | TEXT | Denormalized ticker for display |
| `side` | TEXT | `buy` or `sell` |
| `order_type` | TEXT | `market` or `limit` |
| `time_in_force` | TEXT | `day`, `gtc`, `ioc`, `fok`. Default: `day` |
| `quantity` | NUMERIC(18,8) | Share count (8 decimals for fractional). NULL if notional. |
| `notional` | NUMERIC(14,2) | Dollar amount for fractional orders. NULL if quantity. |
| `limit_price` | NUMERIC(14,4) | Price threshold for limit orders. NULL for market. |
| `filled_quantity` | NUMERIC(18,8) | Shares filled so far. Default: `0`. |
| `filled_avg_price` | NUMERIC(14,4) | Average execution price |
| `status` | TEXT | `pending` → `new` → `accepted` → `filled`. Terminal: `filled`, `canceled`, `expired`, `replaced`, `rejected`, `failed` |
| `is_queued` | BOOL | True when placed outside market hours |
| `submitted_at` | TIMESTAMPTZ | When sent to Alpaca |
| `filled_at` | TIMESTAMPTZ | When completely filled |
| `canceled_at` | TIMESTAMPTZ | When canceled |
| `expired_at` | TIMESTAMPTZ | When expired |
| `failed_at` | TIMESTAMPTZ | When failed |
| `replaced_by` **[FK]** | UUID | Self-ref FK → `orders(id)`. Replacement order. |
| `replaces` **[FK]** | UUID | Self-ref FK → `orders(id)`. Original order. |
| `commission` | NUMERIC(10,4) | Commission charged. Default: `0`. |
| `created_at` | TIMESTAMPTZ | When the user confirmed the trade |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 5.2 `transfers`

ACH money movements in/out of the Alpaca account (FR-4.3, FR-4.11).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `account_id` **[FK]** | UUID | FK → `accounts(id)` |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. For RLS. |
| `bank_link_id` **[FK]** | UUID | FK → `bank_links(id)` |
| `alpaca_transfer_id` | TEXT | Alpaca's transfer ID. UNIQUE. |
| `direction` | TEXT | `incoming` (deposit) or `outgoing` (withdrawal) |
| `amount` | NUMERIC(14,2) | Dollar amount |
| `status` | TEXT | `queued` → `pending` → `approved` → `complete`. Also: `canceled`, `returned` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### `activity_feed` (View)

Unions `orders` and `transfers` into a single timeline for the dashboard (FR-11.6). Ordered by `created_at DESC`.

---

## 6. AI Conversations

Stores persistent chat history, tool call logs, and user feedback for UX (resuming conversations), debugging (tracing bad responses), and continuous improvement (evaluation datasets from feedback).

### 6.1 `conversations`

Container for chat sessions (FR-14).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)` |
| `title` | TEXT | Auto-generated or user-editable |
| `system_prompt_version` | TEXT | Prompt version active at conversation start |
| `is_archived` | BOOL | Soft delete for audit trail preservation |
| `last_message_at` | TIMESTAMPTZ | Denormalized for sorting |
| `message_count` | INT | Denormalized for display |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 6.2 `messages`

Individual chat messages. Includes debugging metadata: token counts, latency, stop reason, and error details.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)` |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. For RLS. |
| `role` | TEXT | `user`, `assistant`, or `system` |
| `content` | TEXT | Message text |
| `sequence_number` | INT | Ordering. UNIQUE on `(conversation_id, sequence_number)`. |
| `input_tokens` | INT | Tokens sent to Claude |
| `output_tokens` | INT | Tokens generated by Claude |
| `model` | TEXT | Claude model version used |
| `latency_ms` | INT | End-to-end API response time |
| `stop_reason` | TEXT | `end_turn`, `max_tokens`, `tool_use`, `stop_sequence` |
| `error_message` | TEXT | NULL if successful; error details on failure |
| `created_at` | TIMESTAMPTZ | When the message was created |

### 6.3 `tool_calls`

Every tool/function call the AI agent makes (FR-5.6). Input, output, status, and execution time are logged.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `message_id` **[FK]** | UUID | FK → `messages(id)` |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)`. Denormalized. |
| `tool_name` | TEXT | Tool called: `get_quote`, `place_order`, `get_portfolio`, etc. |
| `tool_input` | JSONB | Parameters sent to the tool |
| `tool_output` | JSONB | Response from the tool |
| `status` | TEXT | `pending`, `success`, or `error` |
| `duration_ms` | INT | Execution time in milliseconds |
| `created_at` | TIMESTAMPTZ | When the tool call was made |

### 6.4 `message_feedback`

User feedback on agent responses. One rating per message per user.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `message_id` **[FK]** | UUID | FK → `messages(id)`. UNIQUE with `user_id`. |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)`. Denormalized. |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)` |
| `rating` | TEXT | `positive` or `negative` |
| `feedback_text` | TEXT | Optional free-text explanation |
| `feedback_category` | TEXT | Optional tag: `inaccurate`, `unhelpful`, `too_verbose`, `wrong_tool`, `good_explanation`, etc. |
| `created_at` | TIMESTAMPTZ | When feedback was submitted |

### Debugging Flow

Negative feedback → message content & user input → `stop_reason` / `latency_ms` / `error_message` → `tool_calls` for that message → `system_prompt_version` & `model` version. Traces from symptom to root cause.

---

## 7. Audit Trail

### 7.1 `trade_audit_logs`

Regulatory compliance backbone. Every step in a trade flow gets its own row: user request, agent interpretation, confirmation card, risk flags (FR-9.1), user confirmation, and outcome (FR-9.3).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)` |
| `order_id` **[FK]** | UUID | FK → `orders(id)` |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)` |
| `message_id` **[FK]** | UUID | FK → `messages(id)` |
| `action` | TEXT | `trade_requested`, `risk_flagged`, `user_confirmed`, `trade_executed`, `trade_canceled`, `trade_failed` |
| `user_message` | TEXT | Original request text |
| `agent_interpretation` | JSONB | Parsed request: `{ticker, side, quantity, order_type}` |
| `trade_card_data` | JSONB | Confirmation card shown to user (FR-10.2) |
| `risk_flags` | JSONB | Risk warnings shown (FR-9.1) |
| `outcome` | TEXT | `executed`, `canceled`, or `failed` |
| `created_at` | TIMESTAMPTZ | When the audit event was logged |

---

## 8. Watchlists

### 8.1 `watchlists`

Container for watchlist collections (FR-13.1). Users get a default "My Watchlist" on account creation.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)` |
| `name` | TEXT | Default: `My Watchlist` |
| `sort_order` | INT | Display ordering |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 8.2 `watchlist_items`

Individual securities on a watchlist. UNIQUE on `(watchlist_id, security_id)`. Price data comes from `securities` cached columns.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `watchlist_id` **[FK]** | UUID | FK → `watchlists(id)` |
| `security_id` **[FK]** | UUID | FK → `securities(id)` |
| `sort_order` | INT | Display ordering within watchlist |
| `added_at` | TIMESTAMPTZ | When added to the watchlist |

---

## 9. Regulatory Documents

### 9.1 `documents`

Alpaca-generated regulatory documents: trade confirmations, account statements, and tax forms (1099s).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `account_id` **[FK]** | UUID | FK → `accounts(id)` |
| `user_id` **[FK]** | UUID | FK → `auth.users(id)`. For RLS. |
| `alpaca_document_id` | TEXT | Alpaca's document ID. UNIQUE. |
| `document_type` | TEXT | `trade_confirmation`, `account_statement`, `tax_1099` |
| `document_sub_type` | TEXT | Sub-classification if needed |
| `document_date` | DATE | Date the document covers |
| `viewed_at` | TIMESTAMPTZ | When user first viewed. NULL if unviewed. |
| `downloaded_at` | TIMESTAMPTZ | When user downloaded. NULL if not downloaded. |
| `created_at` | TIMESTAMPTZ | When synced from Alpaca |

---

## 10. Config & Infrastructure

### 10.1 `feature_flags`

Global feature flag definitions for controlling beta rollout without code deploys.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `name` | TEXT | Unique identifier: `trade_execution`, `watchlists`, `limit_orders`, `ai_chat`, etc. |
| `enabled_globally` | BOOL | Global on/off switch |
| `description` | TEXT | Human-readable explanation |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 10.2 `user_feature_flags`

Per-user overrides. Composite PK of `(user_id, flag_id)`. Lookup: check user override first, fall back to global flag.

| Column | Type | Description |
|---|---|---|
| `user_id` **[PK/FK]** | UUID | FK → `auth.users(id)` |
| `flag_id` **[PK/FK]** | UUID | FK → `feature_flags(id)` |
| `enabled` | BOOL | Override value |
| `created_at` | TIMESTAMPTZ | When override was created |

### 10.3 `webhook_events`

Durable log of incoming webhooks for idempotent processing. No `user_id`, no RLS — purely backend infrastructure.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `provider` | TEXT | `alpaca` or `plaid` |
| `event_type` | TEXT | `trade_updates`, `transfer_updates`, `account_updates`, etc. |
| `payload` | JSONB | Full raw JSON body |
| `processed` | BOOL | Whether the event has been handled |
| `error_message` | TEXT | NULL on success; error details on failure |
| `idempotency_key` | TEXT | UNIQUE. Prevents duplicate processing. |
| `received_at` | TIMESTAMPTZ | When the webhook arrived |
| `processed_at` | TIMESTAMPTZ | When processing completed |

---

## 11. Relationship Map

| From | To | Type | Purpose |
|---|---|---|---|
| `alpaca_accounts` | `accounts` | 1:1 | Alpaca detail → generic account |
| `bank_links` | `alpaca_accounts` | N:1 | Multiple banks per Alpaca account |
| `orders` | `accounts` | N:1 | Multiple orders per account |
| `orders` | `securities` | N:1 | Multiple orders per security |
| `orders` | `orders` | 1:1 | Self-ref: `replaced_by` / `replaces` |
| `transfers` | `accounts` | N:1 | Multiple transfers per account |
| `transfers` | `bank_links` | N:1 | Multiple transfers per bank |
| `documents` | `accounts` | N:1 | Multiple documents per account |
| `messages` | `conversations` | N:1 | Multiple messages per conversation |
| `tool_calls` | `messages` | N:1 | Multiple tool calls per message |
| `tool_calls` | `conversations` | N:1 | Denormalized for conversation queries |
| `message_feedback` | `messages` | 1:1 | One rating per message per user |
| `message_feedback` | `conversations` | N:1 | Denormalized for conversation queries |
| `trade_audit_logs` | `orders` | N:1 | Multiple audit steps per order |
| `trade_audit_logs` | `conversations` | N:1 | Links trade to originating conversation |
| `trade_audit_logs` | `messages` | N:1 | Links trade to triggering message |
| `watchlist_items` | `watchlists` | N:1 | Multiple items per watchlist |
| `watchlist_items` | `securities` | N:1 | Multiple watchlists per security |
| `user_feature_flags` | `feature_flags` | N:1 | Multiple user overrides per flag |

---

## 12. Infrastructure Details

### 12.1 Row Level Security

Every user-scoped table has RLS enabled with the standard policy: `user_id = auth.uid()`.

**Subquery policies** (no direct `user_id`):
- `watchlist_items` — access granted if `watchlist_id` belongs to a watchlist owned by the current user
- `tool_calls` — access granted if `conversation_id` belongs to a conversation owned by the current user

**Read-only for all authenticated users:** `securities` (reference data) and `feature_flags` (global config).

The backend service role bypasses all RLS for admin operations, webhook processing, and data sync.

### 12.2 Automatic `updated_at` Triggers

A trigger function (`update_updated_at_column`) is applied to every table with an `updated_at` column. On any `UPDATE`, the trigger sets `updated_at = now()` automatically.

### 12.3 Indexes

- **Active orders** — partial index on non-terminal statuses
- **Unprocessed webhooks** — partial index on `processed = false`
- **Non-archived conversations** — partial index for conversation list
- **Negative feedback** — partial index for quality review
- **Portfolio snapshots** — composite index on `(user_id, snapshot_at DESC)`

### 12.4 Cascade Behavior

All user-scoped foreign keys use `ON DELETE CASCADE`:

- `auth.users` → `accounts` → `alpaca_accounts`, `orders`, `transfers`, `documents`
- `conversations` → `messages` → `tool_calls`
- `watchlists` → `watchlist_items`

Account deletion (FR-1.5) cleanly removes all user data without orphaned rows.
