# Sevino Database Schema

**MVP / Closed Beta — v3.0 | March 2026**

| | |
|---|---|
| **Database** | PostgreSQL via Supabase |
| **Tables** | 11 |
| **Platform** | iOS (Swift) + FastAPI |
| **Brokerage** | Alpaca Securities LLC |
| **AI Provider** | Claude (Anthropic) |

---

## Table of Contents

1. [Overview](#1-overview)
   - [Table Summary by Domain](#11-table-summary-by-domain)
2. [Users & Onboarding](#2-users--onboarding)
   - [`user_profiles`](#21-user_profiles)
   - [`user_financial_profiles`](#22-user_financial_profiles)
   - [`user_settings`](#23-user_settings)
3. [Brokerage & Funding](#3-brokerage--funding)
   - [`brokerage_accounts`](#31-brokerage_accounts)
   - [`plaid_items`](#32-plaid_items)
   - [`ach_relationships`](#33-ach_relationships)
4. [AI Radar](#4-ai-radar)
   - [`radar_items`](#41-radar_items)
5. [AI Conversations](#5-ai-conversations)
   - [`conversations`](#51-conversations)
   - [`messages`](#52-messages)
6. [Trading Audit](#6-trading-audit)
   - [`order_events`](#61-order_events)
7. [Config](#7-config)
   - [`feature_flags`](#71-feature_flags)
8. [Relationship Map](#8-relationship-map)

---

## 1. Overview

This document describes the database schema for Sevino's MVP/closed beta release. The schema supports user onboarding, Alpaca brokerage integration, AI-powered chat with tool calling, trade execution, an AI radar watchlist, and bank linking via Plaid.

The database runs on PostgreSQL managed by Supabase. Authentication is handled by Supabase Auth, which provides the `auth.users` table automatically. The `user_profiles` table mirrors `auth.users(id)` as its primary key; all other user-scoped tables reference `user_profiles(id)` via `user_id`.

### 1.1 Table Summary by Domain

| Domain | Tables | Purpose |
|---|---|---|
| Users & Onboarding | `user_profiles`, `user_financial_profiles`, `user_settings` | Profile data, financial questionnaire, app settings |
| Brokerage & Funding | `brokerage_accounts`, `plaid_items`, `ach_relationships` | Alpaca accounts, Plaid bank links, ACH relationships |
| AI Radar | `radar_items` | AI-generated and user-added stock watchlist |
| AI Conversations | `conversations`, `messages` | Chat persistence with tool call logging |
| Trading Audit | `order_events` | Order lifecycle tracking |
| Config | `feature_flags` | Beta rollout control |

---

## 2. Users & Onboarding

Authentication is handled entirely by Supabase Auth. When a user registers, Supabase creates a row in `auth.users` with a UUID primary key. The `user_profiles` table uses the same UUID as its own primary key (`id = auth.users.id`).

### 2.1 `user_profiles`

Core user identity. `id` mirrors `auth.users.id` directly. One row per user.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | `= auth.users.id` |
| `email` | TEXT | User's email address |
| `first_name` | TEXT | First name |
| `last_name` | TEXT | Last name |
| `date_of_birth` | DATE | Date of birth |
| `onboarding_completed` | BOOL | Whether the user has finished onboarding |
| `onboarding_step` | TEXT | Current step in the onboarding flow |
| `last_active_at` | TIMESTAMPTZ | Last activity timestamp |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 2.2 `user_financial_profiles`

Financial questionnaire answers collected during onboarding. Injected into AI conversations for personalized responses. One row per user (1:1 with `user_profiles`).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `date_of_birth` | DATE | Denormalized for AI context |
| `annual_income` | TEXT | Enum bucket |
| `net_worth` | TEXT | Enum bucket |
| `risk_tolerance` | TEXT | `sell` / `hold` / `buy_more` |
| `investment_goals` | TEXT[] | Multi-select array |
| `time_horizon` | TEXT | `1_3y` / `3_7y` / `7_plus` |
| `experience_level` | TEXT | `beginner` / `intermediate` / `advanced` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 2.3 `user_settings`

App-level preferences separate from financial profile data. One row per user (1:1 with `user_profiles`).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `theme` | TEXT | `light` / `dark` / `system` |
| `text_size` | TEXT | `standard` / `large` |
| `notifications_enabled` | BOOL | Push notification toggle |
| `ai_internet_access` | BOOL | Whether AI can access the internet (FR-4.9) |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 3. Brokerage & Funding

### 3.1 `brokerage_accounts`

Alpaca brokerage account linked to a user. One per user at MVP (1:1 with `user_profiles`).

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `alpaca_account_id` | TEXT | Alpaca's account UUID. UNIQUE. |
| `account_status` | TEXT | `SUBMITTED` → `ACTIVE` |
| `account_number` | TEXT | Alpaca account number |
| `kyc_submitted_at` | TIMESTAMPTZ | When KYC was submitted |
| `activated_at` | TIMESTAMPTZ | When account became active |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 3.2 `plaid_items`

Plaid-linked bank accounts. One-to-many with `user_profiles`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `plaid_item_id` | TEXT | Plaid's item identifier |
| `plaid_access_token` | TEXT | Encrypted at rest |
| `institution_name` | TEXT | Bank name |
| `account_mask` | TEXT | Last 4 digits |
| `account_name` | TEXT | Account display name |
| `status` | TEXT | `active` / `error` / `revoked` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 3.3 `ach_relationships`

ACH funding relationships linking a brokerage account to a bank. References both `brokerage_accounts` and optionally `plaid_items`. One-to-many with `user_profiles`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `brokerage_account_id` **[FK]** | UUID | FK → `brokerage_accounts(id)` |
| `plaid_item_id` **[FK]** | UUID | FK → `plaid_items(id)`. Nullable. |
| `alpaca_relationship_id` | TEXT | Alpaca's ACH relationship ID |
| `institution_name` | TEXT | Bank name (e.g. Bank of America) |
| `account_mask` | TEXT | Last 4 digits (e.g. 4832) |
| `account_type` | TEXT | `checking` / `savings` |
| `nickname` | TEXT | User-facing label (e.g. BofA Checking) |
| `status` | TEXT | `QUEUED` → `APPROVED` |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 4. AI Radar

### 4.1 `radar_items`

AI-generated and user-added stock recommendations. AI-generated items expire unless favorited. One-to-many with `user_profiles`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `symbol` | TEXT | Ticker symbol (e.g. `VTI`) |
| `company_name` | TEXT | Cached at creation |
| `context_blurb` | TEXT | AI-generated blurb. Nullable. |
| `source` | TEXT | `ai_generated` / `user_added` |
| `is_favorited` | BOOL | Persists if true (prevents expiry) |
| `relevance_score` | FLOAT | AI ranking score. Nullable. |
| `expires_at` | TIMESTAMPTZ | Null if favorited |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 5. AI Conversations

### 5.1 `conversations`

Container for chat sessions. One-to-many with `user_profiles`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `title` | TEXT | AI-generated summary |
| `preview` | TEXT | First ~100 chars of conversation |
| `started_at` | TIMESTAMPTZ | When conversation began |
| `last_message_at` | TIMESTAMPTZ | Denormalized for sorting |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

### 5.2 `messages`

Individual chat messages. Tool calls and rendered card payloads are stored inline as JSONB. One-to-many with `conversations`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)` |
| `role` | TEXT | `user` / `assistant` / `system` |
| `content` | TEXT | Message text |
| `mcp_cards` | JSONB | Rendered card payloads |
| `tool_calls` | JSONB | Tool invocations |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 6. Trading Audit

### 6.1 `order_events`

Trade order lifecycle tracking. Links orders to users and optionally to the AI conversation that initiated them. Synced via Alpaca SSE. One-to-many with `user_profiles`.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `user_id` **[FK]** | UUID | FK → `user_profiles(id)` |
| `conversation_id` **[FK]** | UUID | FK → `conversations(id)`. Nullable. |
| `alpaca_order_id` | TEXT | Alpaca's order UUID |
| `symbol` | TEXT | Ticker symbol |
| `side` | TEXT | `buy` / `sell` |
| `order_type` | TEXT | `market` / `limit` |
| `qty` | NUMERIC | Share count. Null if notional. |
| `notional` | NUMERIC | Dollar amount. Null if qty. |
| `limit_price` | NUMERIC | Price threshold for limit orders |
| `status` | TEXT | Synced via Alpaca SSE |
| `filled_avg_price` | NUMERIC | Average execution price |
| `filled_qty` | NUMERIC | Shares filled |
| `submitted_at` | TIMESTAMPTZ | When sent to Alpaca |
| `filled_at` | TIMESTAMPTZ | When completely filled |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 7. Config

### 7.1 `feature_flags`

Global feature flag definitions for controlling beta rollout without code deploys.

| Column | Type | Description |
|---|---|---|
| `id` **[PK]** | UUID | Primary key |
| `key` | TEXT | Unique identifier |
| `enabled` | BOOL | On/off switch |
| `description` | TEXT | Human-readable explanation |
| `created_at` | TIMESTAMPTZ | Row creation timestamp |
| `updated_at` | TIMESTAMPTZ | Auto-maintained by trigger |

---

## 8. Relationship Map

| From | FK Column | To | Cardinality |
|---|---|---|---|
| `user_financial_profiles` | `user_id` | `user_profiles` | 1:1 |
| `user_settings` | `user_id` | `user_profiles` | 1:1 |
| `brokerage_accounts` | `user_id` | `user_profiles` | 1:1 |
| `plaid_items` | `user_id` | `user_profiles` | 1:M |
| `ach_relationships` | `user_id` | `user_profiles` | 1:M |
| `ach_relationships` | `brokerage_account_id` | `brokerage_accounts` | M:1 |
| `ach_relationships` | `plaid_item_id` | `plaid_items` | M:1 (nullable) |
| `radar_items` | `user_id` | `user_profiles` | 1:M |
| `conversations` | `user_id` | `user_profiles` | 1:M |
| `messages` | `conversation_id` | `conversations` | 1:M |
| `order_events` | `user_id` | `user_profiles` | 1:M |
| `order_events` | `conversation_id` | `conversations` | 1:M (nullable) |
