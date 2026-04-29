# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sevino is an AI-native brokerage iOS app (part of the `sevino` monorepo). The backend lives in `sevino-api/` — see its own CLAUDE.md for API details. This directory (`sevino-app/Sevino`) is the Xcode project root.

**Stack**: Swift 5 / SwiftUI, Xcode 16+, iOS 17+ deployment target, SPM for dependencies.

## Commands

```bash
# Build & run from CLI
xcodebuild -project Sevino.xcodeproj -scheme Sevino -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 16' build

# Run unit tests
xcodebuild test -project Sevino.xcodeproj -scheme Sevino -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 16'

# Run UI tests
xcodebuild test -project Sevino.xcodeproj -scheme SevinoUITests -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 16'
```

Or in Xcode: `Cmd+R` (run), `Cmd+U` (test), `Cmd+Shift+K` (clean build).

## Configuration

Environment values are set in `Config.xcconfig` (gitignored). Copy from `Config.xcconfig.example`:

| Key | Purpose |
|-----|---------|
| `SUPABASE_URL` | Supabase project URL (local: `http://127.0.0.1:54321`) |
| `SUPABASE_ANON_KEY` | Supabase publishable anon key |
| `API_BASE_URL` | Sevino API base URL (local: `http://127.0.0.1:8000`) |

These are exposed to Swift via Info.plist build settings.

## Dependencies (SPM)

- **Supabase** (`supabase-swift` ^2.0.0) — auth, realtime, storage

## Architecture

The project uses **MVVM** with SwiftUI:

```
Sevino/           # App source
  SevinoApp.swift     # @main entry point
  ContentView.swift   # Root view
  Views/              # SwiftUI view files (planned)
  ViewModels/         # ObservableObject view models (planned)
  Services/           # API client, auth wrapper (planned)
  Models/             # Codable data types (planned)
SevinoTests/      # Unit tests (XCTest)
SevinoUITests/    # UI tests (XCUITest)
```

### Swift concurrency settings

The project enables `SWIFT_APPROACHABLE_CONCURRENCY` and sets `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. All types are `@MainActor` by default — use `nonisolated` explicitly when needed for background work.

## Conventions

### Commits & PRs

Follow the monorepo conventions in the root CLAUDE.md:
- Conventional commits: `<type>(<scope>): <summary>`
- PRs use the template at `.github/PULL_REQUEST_TEMPLATE.md`
- PR description covers the branch's net change, not individual commits

### Code style

- Use SwiftUI's declarative patterns; avoid UIKit unless necessary
- Protocol-based dependency injection for testability (define protocol, conform real + mock implementations)
- Keep views thin — business logic belongs in view models or services
- Money / quantity / percentage fields decode via the `@DecimalString` property wrapper (`Sevino/Utils/DecimalString.swift`) — they arrive as JSON strings, not numbers. Format at the view layer using the `Decimal` extensions in `Sevino/Utils/NumberFormatting.swift` (`asCurrency`, `asSignedCurrency`, `asSignedPercent`, `asShareCount`). Never render `Decimal.description` directly; never decode money as `Double`.
