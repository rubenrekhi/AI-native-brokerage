# Saturn App

iOS app for Saturn — an AI-native brokerage built by [Sevino](https://sevino.ai). Built with Swift and SwiftUI.

## Quick Start

### Prerequisites

- macOS with Xcode 16+
- iOS 17+ deployment target
- Supabase project credentials (URL + anon key)
- Saturn API running locally or pointed at a dev environment

### Setup

1. Open `saturn-app/Saturn.xcodeproj` in Xcode.
2. Create a `Config.xcconfig` file (gitignored) with your environment values:
   ```
   SUPABASE_URL = http://localhost:54321
   SUPABASE_ANON_KEY = your-anon-key
   API_BASE_URL = http://localhost:8000
   API_KEY = your-dev-api-key
   ```
3. Build and run on the iOS Simulator (Cmd+R).

For the full experience locally, you need the Saturn API running — see [saturn-api/README.md](../saturn-api/README.md).

## Project Structure

```
saturn-app/
├── Saturn.xcodeproj
├── Saturn/
│   ├── App/                  # App entry point, app-level config
│   ├── Views/                # SwiftUI views (screens + components)
│   │   ├── Auth/             # Login, signup, onboarding
│   │   ├── Trading/          # Trade execution, natural language input
│   │   ├── Portfolio/        # Holdings, performance charts
│   │   ├── Funding/          # Deposits, withdrawals, bank linking
│   │   └── Chat/             # AI conversation interface
│   ├── ViewModels/           # View models (business logic for views)
│   ├── Services/             # API clients, Supabase auth, Plaid Link
│   │   ├── APIClient.swift   # HTTP client for Saturn API
│   │   ├── AuthService.swift # Supabase Auth wrapper
│   │   └── PlaidService.swift# Plaid Link integration
│   ├── Models/               # Data models (API responses, local state)
│   └── Utils/                # Extensions, helpers, formatters
├── SaturnTests/              # Unit tests
│   ├── ViewModelTests/
│   ├── ServiceTests/
│   └── Mocks/
└── SaturnUITests/            # UI tests (critical flows only)
    └── Flows/
```

## How It Connects to the Backend

All API communication goes through `Services/APIClient.swift`. Every request includes:
- `Authorization: Bearer <jwt>` — Supabase Auth token, managed by `AuthService`.
- `X-API-Key: <key>` — static API key for app identification.

The base URL (`API_BASE_URL`) points to `localhost:8000` in development and the Railway production URL in release builds.

## Authentication

Auth is handled by Supabase via the `supabase-swift` SDK:
- Signup/login methods in `AuthService.swift`.
- JWT and refresh tokens stored and managed automatically by the SDK.
- JWT is attached to every API request by `APIClient.swift`.
- Social logins (Google, Apple) supported via Supabase Auth.

## Key Integrations

### Plaid Link

Bank account linking uses Plaid's native iOS SDK (LinkKit). The flow:
1. App requests a `link_token` from the Saturn API.
2. App opens Plaid Link with the token — user selects their bank and authenticates.
3. Plaid Link returns a `public_token` on success.
4. App sends the `public_token` to the Saturn API, which handles the rest (token exchange → Alpaca ACH link).

### Alpaca (indirect)

The app never talks to Alpaca directly. All trading, portfolio, and account operations go through the Saturn API. The API returns data in app-friendly shapes — the app doesn't need to know about Alpaca's data models.

## Testing

### Unit Tests (SaturnTests/)

Tests for view models, services, data models, and business logic. Uses XCTest (built into Xcode).

**Mocking pattern:** Define protocols for services (e.g., `TradingServiceProtocol`). In production, inject the real implementation. In tests, inject a mock that returns predetermined data. This also benefits SwiftUI previews.

Run in Xcode: Cmd+U or Product → Test.

### UI Tests (SaturnUITests/)

XCUITest for automated UI testing of critical flows. Use sparingly — these are slow and brittle. Focus on:
- Onboarding / KYC flow
- Trade execution flow
- Deposit flow

### Snapshot Tests (later)

Once the UI design stabilizes, add `swift-snapshot-testing` to catch unintended visual regressions. Not needed for MVP.

## CI

Frontend tests run in GitHub Actions on a macOS runner, triggered on changes to `saturn-app/**`.

Workflow:
1. Checkout repo.
2. Build Xcode project.
3. Run XCTest suite.
4. Catches build failures and test regressions before merging.