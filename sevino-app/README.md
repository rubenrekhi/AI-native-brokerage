# Sevino App

iOS app for Sevino — an AI-native brokerage built by [Sevino](https://sevino.ai). Built with Swift and SwiftUI.

## Quick Start

### Prerequisites

- macOS with an Xcode/iOS SDK that can build the checked-in deployment target (`IPHONEOS_DEPLOYMENT_TARGET = 26.2`).
- Swift Package Manager access to GitHub for `supabase-swift`, `plaid-link-ios` (`LinkKit`), and `swift-markdown-ui` (`MarkdownUI`).
- Supabase project credentials (URL + anon key). For local dev, run `supabase status` from `sevino-api/` after `make infra`.
- Sevino API running locally or pointed at a dev/staging environment.

### Setup

1. From the monorepo root, start the backend if you want the full local experience:
   ```bash
   cd sevino-api
   make infra
   make migrate
   make server
   ```
2. Open `sevino-app/Sevino/Sevino.xcodeproj` in Xcode.
3. Copy `sevino-app/Sevino/Config.xcconfig.example` to create per-environment config files (all gitignored):
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
   Use the same `API_KEY` as `sevino-api/.env`; leave it empty locally when the backend key gate is disabled. Use `$()` in URLs to prevent `//` from being parsed as an xcconfig comment.
4. Let Xcode resolve packages, then build and run on the iOS Simulator (Cmd+R).

## Project Structure

```
sevino-app/
└── Sevino/
    ├── Config.xcconfig.example
    ├── Sevino.xcodeproj
    ├── Sevino/
    │   ├── App/                  # @main app, routing/bootstrap, UI test launch hooks
    │   ├── Assets.xcassets/      # Logos, app icon, welcome/sign-up imagery
    │   ├── Models/               # DTOs and UI data models
    │   │   ├── Auth/ Brokerage/ Cards/ Chat/ Digest/ Funding/
    │   │   ├── Home/ MarketData/ Onboarding/ Portfolio/ Settings/ Trading/
    │   │   └── APIError.swift, AssetSearchResult.swift
    │   ├── Services/             # API clients and platform/service adapters
    │   │   ├── Chat/             # SSE parser/client for streamed AI turns
    │   │   ├── APIClient.swift   # REST client with auth/API-key headers
    │   │   ├── Supabase+Client.swift, AuthService.swift
    │   │   ├── FundingService.swift, TradingService.swift, PortfolioService.swift
    │   │   ├── MarketDataService.swift, RadarAPIClient.swift, DigestAPIClient.swift
    │   │   └── SettingsService.swift, ShortcutsAPIClient.swift, UserProfileService.swift
    │   ├── ViewModels/           # App, auth, chat, digest, funding, home, onboarding, portfolio, settings
    │   ├── Views/                # SwiftUI screens and components
    │   ├── Utils/                # AppConfig, JSON coders, formatting, theme, markdown, helpers
    │   └── Resources/Fonts/
    ├── SevinoTests/              # XCTest unit/integration tests with mocks
    └── SevinoUITests/            # XCUITest flows
```

## Backend Connection

Runtime config is read from Info.plist build settings via `Utils/AppConfig.swift`:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `API_BASE_URL`
- `API_KEY`

REST calls go through `Services/APIClient.swift`, which attaches `Authorization: Bearer <jwt>` when a Supabase session exists and `X-API-Key` when `API_KEY` is non-empty. The JSON coders in `Utils/JSONCoders+Sevino.swift` use snake-case/camel-case conversion to match the FastAPI API.

Streamed AI chat turns use `Services/Chat/SSEClient.swift` and `ViewModels/Chat/ConversationStore.swift`. The SSE client attaches the same JWT/API-key headers and parses wire events before the chat model layer decodes them.

## Key Integrations

- **Supabase Auth** — `AuthService` wraps `supabase-swift`, handles session state, social login, token refresh, email verification, and phone verification flows.
- **Sevino API** — all brokerage, trading, portfolio, market data, funding, radar, digest, shortcuts, and settings features call the backend. The app never talks directly to Alpaca, FMP, Anthropic, or Langfuse.
- **Plaid Link** — native LinkKit flow gets a link token from the API, opens Plaid Link, then sends the public token/account selection back to the API for ACH setup.
- **MarkdownUI** — renders assistant/chat markdown blocks using the app theme.

## Testing

### Unit Tests

Run in Xcode with Cmd+U or Product → Test. The suite covers view models, services, DTO decoding, chat/SSE parsing, card data, onboarding, funding, portfolio, settings, and utility logic. Production services are protocol-backed so tests can inject mocks from `SevinoTests/Mocks/`.

### Integration Tests

Some tests are skipped unless `INTEGRATION_TESTS=1` is set in the Xcode scheme environment. Local Supabase/API-backed tests use:

```
INTEGRATION_TESTS = 1
SUPABASE_TEST_URL = http://127.0.0.1:54321
SUPABASE_TEST_ANON_KEY = <from supabase status>
SUPABASE_TEST_SERVICE_ROLE_KEY = <from supabase status>
SEVINO_API_TEST_URL = http://127.0.0.1:8000
```

Start the backend stack first with `make infra`, `make migrate`, and `make server` from `sevino-api/`.

### UI Tests

XCUITest coverage lives in `SevinoUITests/` for critical flows such as welcome/auth and digest. Keep UI tests focused; most business logic belongs in unit tests.

## CI

There is no frontend GitHub Actions workflow checked into `.github/workflows/` right now; the current CI workflow is backend-only. Until a frontend workflow is added, run the Xcode build/test suite locally before merging iOS changes.
