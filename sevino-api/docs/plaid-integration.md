# Plaid Link Integration Guide

> **Sevino Technical Reference** — Bank Account Linking & ACH Funding via Plaid + Alpaca
>
> Version 1.0 • March 2026

---

## Key Principle

- **Sevino NEVER handles raw bank account or routing numbers.**
- Plaid captures credentials client-side via the Plaid Link SDK.
- The backend only handles tokens (link_token, public_token, access_token, processor_token).
- Alpaca retrieves bank details from Plaid directly using the processor token.
- Bank account numbers and routing numbers flow from Plaid → Alpaca. They never touch Sevino's systems.

**PRD References:** FR-3.3, FR-3.4, FR-3.5

---

## Prerequisites

### Accounts Required

| Service | What You Need | Where |
|---|---|---|
| Plaid | Client ID + Secret (Sandbox and Production) | `dashboard.plaid.com` |
| Plaid | Alpaca integration enabled on Plaid account | Plaid Dashboard > Integrations |
| Alpaca | Broker API keys (Sandbox and Production) | `broker-app.alpaca.markets` |
| Alpaca | User must have an **ACTIVE** Alpaca brokerage account | Created via `POST /v1/accounts` |

### Plaid Dashboard Configuration

Before writing any code, configure the following in the Plaid Dashboard:

1. **Enable the Alpaca integration:** Go to Integrations and activate the Alpaca processor. This allows Plaid to generate Alpaca-specific processor tokens.
2. **Enable the Auth product:** Plaid Link must be initialized with the `"auth"` product to access bank account and routing number information.
3. **Configure Link customization:** In the Link customization UI, select the use cases you're powering with Alpaca so Plaid can request appropriate authorization and consent from end users.
4. **Account Select:** Set to **"enabled for one account"** in the Plaid Dashboard. This ensures the user selects a single bank account, and the `accounts` array returned by Plaid always contains exactly one item.

### Plaid Environments

| Environment | Base URL | Credentials |
|---|---|---|
| Sandbox | `https://sandbox.plaid.com` | Test with `user_good` / `pass_good` |
| Production | `https://production.plaid.com` | Real bank credentials |

Plaid's Sandbox simulates the full Link flow without connecting to real banks. Use it during development alongside Alpaca's sandbox.

---

## End-to-End Flow

The complete bank linking flow involves six steps across three actors: the Sevino mobile app (client), the Sevino backend (server), and the Plaid/Alpaca APIs.

```
Mobile App          Sevino Backend          Plaid API          Alpaca API
    |                     |                    |                    |
    |  request link_token |                    |                    |
    |-------------------->|                    |                    |
    |                     |  Step 1: POST      |                    |
    |                     |  /link/token/create |                    |
    |                     |------------------->|                    |
    |                     |    link_token       |                    |
    |                     |<-------------------|                    |
    |    link_token        |                    |                    |
    |<--------------------|                    |                    |
    |                     |                    |                    |
    | Step 2: Open Plaid  |                    |                    |
    | Link SDK            |                    |                    |
    | (user authenticates |                    |                    |
    |  with bank)         |                    |                    |
    |                     |                    |                    |
    | public_token +      |                    |                    |
    | account_id          |                    |                    |
    |-------------------->|                    |                    |
    |                     |  Step 3: POST      |                    |
    |                     |  /item/public_token |                    |
    |                     |  /exchange          |                    |
    |                     |------------------->|                    |
    |                     |   access_token      |                    |
    |                     |<-------------------|                    |
    |                     |                    |                    |
    |                     |  Step 4: POST      |                    |
    |                     |  /processor/token  |                    |
    |                     |  /create           |                    |
    |                     |------------------->|                    |
    |                     |  processor_token    |                    |
    |                     |<-------------------|                    |
    |                     |                    |                    |
    |                     |  Step 5: POST                           |
    |                     |  /v1/accounts/{id}/ach_relationships    |
    |                     |---------------------------------------->|
    |                     |            relationship_id               |
    |                     |<----------------------------------------|
    |                     |                    |                    |
    |  success + confirm  |                    |                    |
    |<--------------------|                    |                    |
    |                     |                    |                    |
    | (later, user        |  Step 6: POST                          |
    |  requests deposit)  |  /v1/accounts/{id}/transfers           |
    |-------------------->|---------------------------------------->|
    |                     |           transfer queued                |
    |                     |<----------------------------------------|
```

---

### Step 1: Create a Link Token (Backend)

**Endpoint:** `POST https://sandbox.plaid.com/link/token/create`

**Production:** `POST https://production.plaid.com/link/token/create`

Before opening Plaid Link on the mobile app, the backend creates a short-lived `link_token`.

**Request body:**

```json
{
  "client_id": "<PLAID_CLIENT_ID>",
  "secret": "<PLAID_SECRET>",
  "user": {
    "client_user_id": "<sevino_internal_user_id>"
  },
  "client_name": "Sevino",
  "products": ["auth"],
  "country_codes": ["US"],
  "language": "en"
}
```

| Parameter | Value | Notes |
|---|---|---|
| `client_id` | Your Plaid client ID | From Plaid Dashboard |
| `secret` | Your Plaid secret | From Plaid Dashboard |
| `user.client_user_id` | Sevino's internal user ID | Unique per user |
| `client_name` | `"Sevino"` | Shown to user in Link UI |
| `products` | `["auth"]` | **Required** for bank account access |
| `country_codes` | `["US"]` | US banks only |
| `language` | `"en"` | English |

**Response:** Contains a `link_token` (valid for **4 hours**). Send this token to the mobile app.

---

### Step 2: Open Plaid Link (Mobile App)

The mobile app uses the Plaid Link SDK to open the Link UI. The user:

1. Sees a bank selection screen
2. Authenticates with their bank credentials
3. Handles MFA if prompted by their bank
4. Selects which account to use for transfers

Plaid Link handles all complexity: bank search, credential input, MFA, error handling, and consent.

**On success, Plaid Link returns two values to the mobile app:**

- `public_token` — a **one-time use** token representing the authenticated session
- `account_id` — the ID of the specific bank account the user selected

**The mobile app sends both values to the Sevino backend.** The `public_token` is short-lived and must be exchanged quickly (Step 3).

---

### Step 3: Exchange Public Token for Access Token (Backend)

**Endpoint:** `POST https://sandbox.plaid.com/item/public_token/exchange`

**Production:** `POST https://production.plaid.com/item/public_token/exchange`

Exchange the one-time `public_token` for a permanent `access_token`.

**Request body:**

```json
{
  "client_id": "<PLAID_CLIENT_ID>",
  "secret": "<PLAID_SECRET>",
  "public_token": "<public_token_from_step_2>"
}
```

**Response:**

```json
{
  "access_token": "access-sandbox-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "item_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "request_id": "..."
}
```

**Store `access_token` and `item_id` securely in your database** (encrypted). You need these for:

- Creating the processor token (next step)
- Future re-authentication if the bank connection expires
- Creating additional processor tokens for the same bank connection

---

### Step 4: Create Processor Token (Backend)

**Endpoint:** `POST https://sandbox.plaid.com/processor/token/create`

**Production:** `POST https://production.plaid.com/processor/token/create`

This is the **critical step**. Generate a processor token scoped specifically for Alpaca.

**Request body:**

```json
{
  "client_id": "<PLAID_CLIENT_ID>",
  "secret": "<PLAID_SECRET>",
  "access_token": "<access_token_from_step_3>",
  "account_id": "<account_id_from_step_2>",
  "processor": "alpaca"
}
```

**Response:**

```json
{
  "processor_token": "processor-sandbox-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "request_id": "..."
}
```

**What the processor token does:**

- It's a secure reference that lets Alpaca (and **only** Alpaca) retrieve the bank account and routing number from Plaid.
- Sevino's backend never sees the actual bank account numbers — they flow directly from Plaid to Alpaca.
- The processor token is **single-purpose** — it can only be used with the specified processor (Alpaca).
- **Do NOT store** the processor token — it's consumed by Alpaca in Step 5 and not needed after that.

---

### Step 5: Create ACH Relationship at Alpaca (Backend)

**Endpoint:** `POST /v1/accounts/{account_id}/ach_relationships`

Pass the processor token to Alpaca. Alpaca makes a server-to-server call to Plaid, retrieves the bank details, and creates the ACH relationship.

**Request body:**

```json
{
  "processor_token": "<processor_token_from_step_4>"
}
```

**Response:**

```json
{
  "id": "794c3c51-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "account_id": "9d587d7a-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "QUEUED",
  "account_owner_name": "Riley Johnson",
  "nickname": "Bank of America Checking"
}
```

**Store `id` (the `relationship_id`)** in your database associated with the user. This is the **only piece of data you need** to initiate future deposits and withdrawals.

---

### Step 6: Initiate Transfers (Backend)

**Endpoint:** `POST /v1/accounts/{account_id}/transfers`

Once the ACH relationship exists, depositing or withdrawing is a single Alpaca REST call.

**Deposit request body:**

```json
{
  "transfer_type": "ach",
  "relationship_id": "<relationship_id_from_step_5>",
  "amount": "500.00",
  "direction": "INCOMING"
}
```

**Withdrawal request body:**

```json
{
  "transfer_type": "ach",
  "relationship_id": "<relationship_id_from_step_5>",
  "amount": "200.00",
  "direction": "OUTGOING"
}
```

**Key facts:**

- The user **never re-authenticates** with Plaid for subsequent transfers
- The ACH relationship persists until the user explicitly unlinks the bank account
- `direction`: `INCOMING` = deposit into brokerage, `OUTGOING` = withdrawal to bank
- Transfer response returns immediately with initial status

**Transfer lifecycle:** `QUEUED → PENDING → COMPLETE` (or `REJECTED`)

**Monitor via SSE:** `GET /v1/events/transfers/status`

- ACH settlement: **1–3 business days** (production)
- Sandbox: **10–30 minutes** simulated delay

---

## Flow Summary Table

| Step | Actor | Action | Result |
|---|---|---|---|
| 1 | Backend | `POST /link/token/create` to Plaid | `link_token` |
| 2 | Mobile App | Open Plaid Link SDK with `link_token` | `public_token` + `account_id` |
| 3 | Backend | `POST /item/public_token/exchange` to Plaid | `access_token` |
| 4 | Backend | `POST /processor/token/create` to Plaid (processor: `"alpaca"`) | `processor_token` |
| 5 | Backend | `POST /v1/accounts/{id}/ach_relationships` to Alpaca | `relationship_id` |
| 6 | Backend | `POST /v1/accounts/{id}/transfers` to Alpaca | Transfer initiated |

**Steps 1–5 happen once per bank account. Step 6 is repeated for every deposit or withdrawal.**

---

## What to Store in the Database

| Data | Store? | Notes |
|---|---|---|
| Plaid `access_token` | **Yes** | **Encrypted.** Needed for creating additional processor tokens, handling Plaid Link re-authentication. |
| Plaid `account_id` | **Yes** | The specific bank account the user selected. Needed alongside `access_token`. |
| Plaid `item_id` | **Yes** | Represents the bank connection. Useful for handling Plaid webhooks (item errors, account updates). |
| Alpaca `relationship_id` | **Yes** | The ACH relationship ID. Used for **all** deposit/withdrawal calls. |
| `processor_token` | **No** | Already consumed by Alpaca in Step 5. Not needed after that. |
| Bank account number | **No** | **Never touches your system.** Flows from Plaid to Alpaca directly. |
| Routing number | **No** | **Never touches your system.** Flows from Plaid to Alpaca directly. |

### Suggested Database Schema

```sql
CREATE TABLE linked_bank_accounts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),
  plaid_access_token  TEXT NOT NULL,       -- encrypted at rest
  plaid_account_id    TEXT NOT NULL,
  plaid_item_id       TEXT NOT NULL,
  alpaca_relationship_id  TEXT NOT NULL,    -- used for all transfers
  account_owner_name  TEXT,                -- from Alpaca response
  nickname            TEXT,                -- e.g. "Bank of America Checking"
  status              TEXT NOT NULL DEFAULT 'QUEUED',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_linked_bank_accounts_user ON linked_bank_accounts(user_id);
```

---

## Plaid Link SDK Integration

Plaid provides native SDKs for React Native, iOS (Swift), and Android (Kotlin).

### React Native

**Package:** `react-native-plaid-link-sdk`

```bash
npm install react-native-plaid-link-sdk
```

**Key callbacks to handle:**

| Callback | When | What You Get | Action |
|---|---|---|---|
| `onSuccess` | User successfully linked bank | `public_token`, `accounts` array | Send `public_token` + `accounts[0].id` to backend for Steps 3–5 |
| `onExit` | User closed Link without completing | `error` object (may be null) | Check error for details. Could be intentional close or an error. |
| `onEvent` | User interaction events | Event name (opened, selected institution, submitted credentials) | Analytics tracking |

**Usage pattern:**

```jsx
import { PlaidLink } from 'react-native-plaid-link-sdk';

<PlaidLink
  tokenConfig={{
    token: linkToken,  // from Step 1
    noLoadingState: false,
  }}
  onSuccess={(success) => {
    const publicToken = success.publicToken;
    const accountId = success.metadata.accounts[0].id;
    // Send to backend for Steps 3-5
    submitBankLink(publicToken, accountId);
  }}
  onExit={(exit) => {
    if (exit.error) {
      // Handle error
      console.error(exit.error.displayMessage);
    }
    // User closed Link
  }}
>
  <LinkButton />
</PlaidLink>
```

### iOS Native (Swift)

**Package:** `LinkKit` (via CocoaPods or SPM)

Same flow: create a `LinkTokenConfiguration` with the `link_token`, present the Link view controller, handle `onSuccess` / `onExit` delegates.

### Android Native (Kotlin)

**Package:** `com.plaid.link` (via Maven)

```groovy
implementation "com.plaid.link:sdk-core:x.x.x"
```

Same flow: create a `LinkTokenConfiguration`, launch the PlaidLink activity, handle the result via `ActivityResultContract`.

---

## Error Handling

### Plaid Link Errors

| Error | Meaning | Action |
|---|---|---|
| `INVALID_CREDENTIALS` | User entered wrong bank login | Plaid Link handles retry automatically |
| `INSTITUTION_NOT_RESPONDING` | Bank is temporarily unavailable | Show "try again later" message |
| `ITEM_LOGIN_REQUIRED` | Bank connection expired (production) | Re-launch Plaid Link in **update mode** with same `access_token` |
| `USER_SETUP_REQUIRED` | User needs to complete setup at their bank | Inform user to check their bank app |

### Alpaca ACH Errors

| Scenario | Alpaca Response | Action |
|---|---|---|
| Invalid processor token | `400 Bad Request` | Token was malformed or already used. Regenerate from Step 4. |
| Account not ACTIVE | `403 Forbidden` | User's Alpaca account isn't ready yet. Wait for KYC approval. |
| Duplicate relationship | `409 Conflict` | Bank account already linked. Show existing relationship. |
| Transfer rejected (NSF) | Transfer status → `REJECTED` | Notify user. Consider restricting future instant funding. |

### Plaid Link Re-authentication (Production)

Bank connections can expire in production (bank rotates credentials, user changes password, MFA requirements change). When this happens:

1. Plaid sends an `ITEM_LOGIN_REQUIRED` error
2. Re-launch Plaid Link in **"update mode"** — pass the existing `access_token` to Plaid Link so the user re-authenticates without creating a new connection
3. The processor token and ACH relationship **remain valid** after re-authentication

**To create a link token for update mode:**

```json
{
  "client_id": "<PLAID_CLIENT_ID>",
  "secret": "<PLAID_SECRET>",
  "user": {
    "client_user_id": "<sevino_internal_user_id>"
  },
  "client_name": "Sevino",
  "access_token": "<existing_access_token>",
  "country_codes": ["US"],
  "language": "en"
}
```

Note: when using `access_token` for update mode, do **not** include the `products` field.

---

## Sandbox Testing

### Plaid Sandbox Credentials

| Field | Value |
|---|---|
| Username | `user_good` |
| Password | `pass_good` |
| MFA (if prompted) | `1234` |

These credentials work with any bank shown in the Plaid Link Sandbox.

### Backend Testing Shortcut (No Link UI)

**Endpoint:** `POST https://sandbox.plaid.com/sandbox/public_token/create`

Bypasses the Plaid Link UI entirely. Gives you a `public_token` you can exchange for an `access_token` and then a `processor_token`. Useful for automated testing and CI/CD pipelines.

**Request body:**

```json
{
  "client_id": "<PLAID_CLIENT_ID>",
  "secret": "<PLAID_SECRET>",
  "institution_id": "ins_109508",
  "initial_products": ["auth"]
}
```

### End-to-End Test Checklist

1. Create a `link_token` from your backend
2. Open Plaid Link on the mobile app with the `link_token`
3. Authenticate with `user_good` / `pass_good`
4. Receive `public_token` and `account_id` in the success callback
5. Exchange `public_token` for `access_token`
6. Create `processor_token` with `processor: "alpaca"`
7. Pass `processor_token` to Alpaca's ACH relationships endpoint
8. Verify the ACH relationship was created (status: `QUEUED`)
9. Initiate a test deposit via Alpaca's transfers endpoint
10. Verify the deposit reflects on the user's balance (**10–30 min** in Alpaca sandbox)

---

## Complete API Endpoint Reference

### Plaid Endpoints

| Endpoint | Method | Purpose | When |
|---|---|---|---|
| `/link/token/create` | `POST` | Create a `link_token` for Plaid Link | Before opening Link UI |
| `/item/public_token/exchange` | `POST` | Exchange `public_token` for `access_token` | After user completes Link |
| `/processor/token/create` | `POST` | Create Alpaca `processor_token` | After token exchange |
| `/sandbox/public_token/create` | `POST` | Create test `public_token` (**sandbox only**) | Backend testing only |

**Base URLs:**

- Sandbox: `https://sandbox.plaid.com`
- Production: `https://production.plaid.com`

### Alpaca Endpoints

| Endpoint | Method | Purpose | When |
|---|---|---|---|
| `/v1/accounts/{id}/ach_relationships` | `POST` | Create ACH relationship with processor token | After processor token created |
| `/v1/accounts/{id}/ach_relationships` | `GET` | List existing ACH relationships | Settings UI |
| `/v1/accounts/{id}/ach_relationships/{rel_id}` | `DELETE` | Remove a linked bank account | User unlinks bank |
| `/v1/accounts/{id}/transfers` | `POST` | Initiate deposit or withdrawal | User requests transfer |
| `/v1/accounts/{id}/transfers` | `GET` | List transfer history and statuses | Settings UI |
| `/v1/events/transfers/status` | `GET` (SSE) | Stream transfer status updates | Backend listener |

### Plaid Link Mobile SDKs

| Platform | Package | Install |
|---|---|---|
| React Native | `react-native-plaid-link-sdk` | `npm install react-native-plaid-link-sdk` |
| iOS (Swift) | `LinkKit` | CocoaPods or Swift Package Manager |
| Android (Kotlin) | `com.plaid.link` | Maven: `implementation "com.plaid.link:sdk-core:x.x.x"` |

---

## Implementation Quick Reference

### Token Lifecycle

| Token | Created By | Lifespan | Stored? |
|---|---|---|---|
| `link_token` | Sevino backend (via Plaid) | 4 hours | No — ephemeral, passed to mobile app |
| `public_token` | Plaid Link SDK (mobile) | Minutes — exchange immediately | No — ephemeral, exchanged in Step 3 |
| `access_token` | Plaid (via token exchange) | Permanent (until connection expires) | **Yes — encrypted in DB** |
| `processor_token` | Plaid (via processor endpoint) | Single use | No — consumed by Alpaca in Step 5 |
| `relationship_id` | Alpaca (via ACH creation) | Permanent (until user unlinks) | **Yes — in DB** |

### Backend Service Methods (Suggested)

```
PlaidService:
  createLinkToken(userId: string) → string (link_token)
  exchangePublicToken(publicToken: string) → { accessToken, itemId }
  createProcessorToken(accessToken: string, accountId: string) → string (processor_token)

AlpacaFundingService:
  createAchRelationship(alpacaAccountId: string, processorToken: string) → AchRelationship
  listAchRelationships(alpacaAccountId: string) → AchRelationship[]
  deleteAchRelationship(alpacaAccountId: string, relationshipId: string) → void
  initiateTransfer(alpacaAccountId: string, relationshipId: string, amount: string, direction: "INCOMING" | "OUTGOING") → Transfer
  listTransfers(alpacaAccountId: string) → Transfer[]

BankLinkingOrchestrator:
  linkBankAccount(userId: string, publicToken: string, accountId: string) → void
    // Orchestrates Steps 3 → 4 → 5 in sequence
    // Stores access_token, account_id, item_id, relationship_id in DB
```
