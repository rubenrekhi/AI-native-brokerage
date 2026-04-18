# Sevino App

iOS app for Sevino — an AI-native brokerage built by [Sevino](https://sevino.ai). Built with Swift and SwiftUI.

## Quick Start

### Prerequisites

- macOS with Xcode 16+
- iOS 17+ deployment target
- Supabase project credentials (URL + anon key)
- Sevino API running locally or pointed at a dev environment

### Setup

1. Open `sevino-app/Sevino/Sevino.xcodeproj` in Xcode.
2. Copy `Config.xcconfig.example` to create per-environment config files (all gitignored):
   - `Config.debug.xcconfig` — local development (Cmd+R)
   - `Config.staging.xcconfig` — TestFlight / staging builds
   - `Config.release.xcconfig` — App Store / production builds

   Example for local dev (`Config.debug.xcconfig`):
   ```
   SUPABASE_URL = http:/$()/127.0.0.1:54321
   SUPABASE_ANON_KEY = your-local-anon-key
   API_BASE_URL = http:/$()/127.0.0.1:8000
   API_KEY =
   ```
   Note: Use `$()` in URLs to prevent `//` being parsed as an xcconfig comment.
3. Build and run on the iOS Simulator (Cmd+R).

For the full experience locally, you need the Sevino API running — see [sevino-api/README.md](../sevino-api/README.md).

## Project Structure

```
sevino-app/
├── Sevino.xcodeproj
├── Config.xcconfig.example       # Template for per-environment configs
├── Sevino/
│   ├── App/
│   │   └── SevinoApp.swift       # @main entry point
│   ├── Views/                    # SwiftUI views (screens + components)
│   │   ├── ContentView.swift     # Root view / navigation shell
│   │   ├── Auth/                 # Login, sign-up, phone number screens
│   │   ├── Onboarding/           # Multi-step onboarding flow (phase 1)
│   │   ├── AlpacaSetup/          # KYC / brokerage account setup (phase 2)
│   │   ├── Home/                 # Home screen
│   │   ├── Trading/              # (placeholder)
│   │   ├── Portfolio/            # (placeholder)
│   │   ├── Funding/              # (placeholder)
│   │   ├── Chat/                 # (placeholder)
│   │   └── Components/           # (placeholder)
│   ├── ViewModels/
│   │   ├── Auth/
│   │   │   ├── AuthViewModel.swift       # Observable auth state for views
│   │   │   └── PhoneNumberViewModel.swift
│   │   └── Home/
│   │       └── HomeViewModel.swift
│   ├── Services/
│   │   ├── APIClient.swift       # HTTP client (conforms to APIClientProtocol); snake_case encoding/decoding; GET/POST/PUT/PATCH/DELETE
│   │   ├── AuthService.swift     # Supabase Auth wrapper (protocol-backed)
│   │   ├── OnboardingService.swift  # Calls PATCH /v1/onboarding, POST /v1/onboarding/submit, GET /v1/onboarding/status
│   │   └── Supabase+Client.swift # SupabaseClient singleton
│   ├── Models/
│   │   ├── APIError.swift        # Structured error model matching backend format
│   │   └── Onboarding/
│   │       └── OnboardingModels.swift  # Request/response Codable types for onboarding API
│   └── Utils/
│       ├── AppConfig.swift           # Reads xcconfig values from Info.plist at runtime
│       ├── AnyCodable.swift          # Type-erased Codable wrapper (for APIError.detail)
│       └── OnboardingDataMapper.swift  # Pure functions: date formatting, name splitting, value normalization
├── SevinoTests/
│   ├── Auth/
│   │   ├── AuthViewModelTests.swift
│   │   ├── AuthServiceIntegrationTests.swift
│   │   └── PhoneNumberViewModelTests.swift
│   ├── Models/
│   │   ├── APIErrorTests.swift
│   │   └── AnyCodableTests.swift
│   ├── Onboarding/
│   │   ├── OnboardingServiceTests.swift
│   │   └── OnboardingDataMapperTests.swift
│   └── Mocks/
│       ├── MockAuthService.swift
│       └── MockAPIClient.swift   # Implements APIClientProtocol for test injection
└── SevinoUITests/                # UI tests (critical flows only)
```

## How It Connects to the Backend

All API communication goes through `Services/APIClient.swift`, which conforms to `APIClientProtocol`. Every request includes:
- `Authorization: Bearer <jwt>` — Supabase Auth token, managed by `AuthService`.
- `X-API-Key: <key>` — static API key for app identification.

`APIClient` uses `JSONEncoder` with `.convertToSnakeCase` and `JSONDecoder` with `.convertFromSnakeCase`, so Swift camelCase model fields map automatically to the backend's snake_case JSON.

The base URL (`API_BASE_URL`) points to `localhost:8000` in development and the Railway production URL in release builds. Non-2xx responses are decoded into a structured `APIError` model (with `error`, `code`, and `detail` fields matching the backend's error format).

`APIClientProtocol` allows injecting `MockAPIClient` in unit tests without network calls.

## Authentication

Auth is handled by Supabase via the `supabase-swift` SDK:
- `AuthService` wraps Supabase auth and listens to auth state changes (sign in, sign out, token refresh) via an async stream.
- Conforms to `AuthServiceProtocol` for dependency injection — tests use `MockAuthService`.
- `AuthViewModel` observes `AuthService` and exposes auth state (`isAuthenticated`, `isLoading`, `authError`) to SwiftUI views.
- JWT is attached to every API request by `APIClient` (reads the token from `AuthService.accessToken`).
- Social logins (Google, Apple) supported via Supabase Auth.

## Key Integrations

### Plaid Link

Bank account linking uses Plaid's native iOS SDK (LinkKit). The flow:
1. App requests a `link_token` from the Sevino API.
2. App opens Plaid Link with the token — user selects their bank and authenticates.
3. Plaid Link returns a `public_token` on success.
4. App sends the `public_token` to the Sevino API, which handles the rest (token exchange → Alpaca ACH link).

### Alpaca (indirect)

The app never talks to Alpaca directly. All trading, portfolio, and account operations go through the Sevino API. The API returns data in app-friendly shapes — the app doesn't need to know about Alpaca's data models.

## Testing

### Unit Tests (SevinoTests/)

Tests for view models, services, data models, and business logic. Uses XCTest (built into Xcode).

**Mocking pattern:** Define protocols for services (e.g., `AuthServiceProtocol`, `APIClientProtocol`). In production, inject the real implementation. In tests, inject a mock that returns predetermined data (see `MockAuthService`, `MockAPIClient`). This also benefits SwiftUI previews.

Run in Xcode: Cmd+U or Product → Test.

### UI Tests (SevinoUITests/)

XCUITest for automated UI testing of critical flows. Use sparingly — these are slow and brittle. Focus on:
- Onboarding / KYC flow
- Trade execution flow
- Deposit flow

### Snapshot Tests (later)

Once the UI design stabilizes, add `swift-snapshot-testing` to catch unintended visual regressions. Not needed for MVP.

## CI

Frontend tests run in GitHub Actions on a macOS runner, triggered on changes to `sevino-app/**`.

Workflow:
1. Checkout repo.
2. Build Xcode project.
3. Run XCTest suite.
4. Catches build failures and test regressions before merging.