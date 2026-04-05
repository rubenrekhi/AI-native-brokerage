# GitHub Copilot Code Review Instructions

Saturn is an AI-native brokerage app. This monorepo contains:
- **saturn-api/** — FastAPI backend (Python 3.12)
- **saturn-app/** — iOS app (Swift/SwiftUI, Xcode 16+, iOS 17+)

When reviewing pull requests, enforce the rules below. Flag violations with exact file paths and line numbers. Provide a concrete fix for each violation. If code is clean, say so — don't invent problems.

---

## Frontend (Swift/SwiftUI) Rules

### 1. Design System — Saturn Tokens

#### Localization
- Never hardcode strings in views. Always use `L10n.*` keys.
- Flag `Text("...")`, `Label("...")`, `Button("...")`, `.navigationTitle("...")` with raw string literals instead of `L10n` references.
- Exempt: SF Symbol names, format specifiers, and `#Preview` blocks.

#### Colour Palette
- Never use raw `Color` literals, hex values, or system colours (`.white`, `.black`, `.gray`) in views. Always use `Color.saturn*` tokens from `Color+Theme.swift`.
- Screen-specific colours go in a local scoped file, not in `Color+Theme.swift`.

#### Font Family
- Never use raw `.custom("DMSerifText-...")` calls. Use `.dmSerif(size:)` / `.dmSerifItalic(size:)` from `Font+Theme.swift`.
- Never use `.custom(...)` for SF Pro — use `.system(size:weight:)` or semantic styles.
- DM Serif Text should only appear in display/hero headings. Most text is SF Pro.

#### Liquid Glass
- Never call `.glassEffect(...)` or `.background(.ultraThinMaterial, ...)` directly. Always use `SaturnGlass.*` modifiers.
- `.modifier(SaturnGlass.*)` must come AFTER layout modifiers (padding, frame, font, foregroundStyle).
- Multiple glass elements must be wrapped in `GlassEffectContainer`.
- Use `.buttonStyle(.glass)` or `.buttonStyle(.glassProminent)` for glass buttons.

### 2. MVVM Architecture
- Views must be thin — no service calls, no `Task { await someService.fetch() }` in views. All async work goes through a ViewModel method.
- Use `@Observable`, not `ObservableObject` / `@Published`.
- ViewModel read-only properties must be `private(set)`.
- Inject dependencies via protocols — `init(service: SomeProtocol = SomeService.shared)`. Never accept concrete service types.
- Views must not reference services directly — no importing or calling `AuthService`, `APIClient`, etc. from a view.
- Naming: `{Feature}ViewModel` in `ViewModels/{Feature}/`. Views: `{Feature}View` in `Views/{Feature}/`.
- Async error/loading/data pattern: clear error, `isLoading = true`, `defer { isLoading = false }`, try/catch, set error on failure.

### 3. SwiftUI View Patterns
- Use `.task { }` modifier, not `Task { }` in `onAppear`.
- Avoid `AnyView` — use `@ViewBuilder`, `Group`, or concrete `some View` returns.
- Extract subviews when view body exceeds ~60 lines. Prefer dedicated `View` structs over computed `some View` properties.
- Use stable, unique IDs for `ForEach` — use model `.id` or `Identifiable` conformance, never array indices.
- Don't store `@Observable` ViewModels in `@State` — `@State` is for view-local value types.
- `@State` must be `private`.
- One type per Swift file (small private subview structs in the same file are fine).
- `Button("Label", action: save)` over `Button("Label") { save() }` for single method calls.
- Extract non-trivial button actions, `.task` blocks, `.onChange` handlers into private methods.
- Keep a stable view tree — avoid top-level `if/else` that swaps entire root branches.
- Ternary for modifier toggling — `.opacity(isVisible ? 1 : 0)` preserves structural identity.
- Never use `onTapGesture()` instead of `Button` unless you need tap location or count.
- Make model structs `Identifiable`.
- Avoid `Binding(get:set:)` in body.

### 4. Swift Type Safety & Concurrency
- No force unwraps (`!`) except in tests and previews.
- No force casts (`as!`).
- Avoid `Any` / `[String: Any]` — use `Codable` structs.
- Use `@MainActor` instead of `DispatchQueue.main`.
- Use `async/await`, not completion handlers or Combine for one-shot operations.
- Exhaustive `switch` — avoid `default` on enums you own.
- `Task.sleep(for:)` not `Task.sleep(nanoseconds:)`.
- Flag `Task.detached()`.
- `if let value {` shorthand, not `if let value = value {`.
- Omit `return` for single-expression functions and computed properties.
- Never use `String(format:)` — use FormatStyle APIs.
- `count(where:)` over `filter().count`.
- `Date.now` over `Date()`.
- Don't create formatters in `body` — they're recreated every render.
- No sorting or filtering inside `body` — precompute in the ViewModel.

### 5. Deprecated API

Flag these and suggest the modern replacement:

| Deprecated | Use instead |
|---|---|
| `foregroundColor()` | `foregroundStyle()` |
| `cornerRadius()` | `clipShape(.rect(cornerRadius:))` |
| `NavigationView` | `NavigationStack` or `NavigationSplitView` |
| `NavigationLink(destination:)` | `navigationDestination(for:)` |
| `.navigationBarLeading/Trailing` | `.topBarLeading/Trailing` |
| `PreviewProvider` | `#Preview { }` |
| `showsIndicators: false` | `.scrollIndicators(.hidden)` |
| 1-parameter `onChange()` | 0- or 2-parameter variant |
| `animation(_:)` without value | `.animation(.bouncy, value: x)` |
| `tabItem()` | `Tab` API with value-based selection |
| `onAppear` for async work | `.task { }` |

### 6. Navigation
- Use `NavigationStack` with typed `NavigationPath`, not `NavigationView`.
- One `NavigationStack` per tab.
- Use `navigationDestination(for:)` with `Hashable` route enums.
- Never mix `navigationDestination(for:)` and `NavigationLink(destination:)`.
- `sheet(item:)` over `sheet(isPresented:)` for optional data.

### 7. Accessibility & UX
- Accessibility labels on all non-text interactive elements.
- Support Dynamic Type — don't use fixed-height frames that clip text.
- Respect `prefers-reduced-motion`.
- Loading states must cover all dependent UI.
- Disable buttons when data isn't ready — `.disabled(viewModel.isLoading)`.
- Buttons with image labels must include text for VoiceOver.
- 44x44 minimum tap target.
- Use `ContentUnavailableView` for empty/error states.
- Use `Label` for icon + text pairs.
- Flag decorative images without `Image(decorative:)` or `.accessibilityHidden(true)`.

### 8. Responsive Layout
- All hardcoded sizes must scale with screen width — define a width-based scale factor (`let s = UIScreen.main.bounds.width / 393`) and multiply point values by it.
- Never use manual line breaks (`\n`) in display strings.
- Use `.fixedSize(horizontal: false, vertical: true)` on multiline text.
- Background images via `.background {}`, not root `ZStack`.

### 9. Performance
- Use `LazyVStack` / `LazyHStack` for large or dynamic-length lists inside `ScrollView`.
- Avoid `id: \.self` on `ForEach` — use a stable domain identifier.
- Narrow the observation surface — pass narrow derived inputs to leaf views.

### 10. Hygiene
- Never store sensitive data in `@AppStorage` / `UserDefaults` — passwords, tokens, API keys go in Keychain.
- Don't swallow user-facing errors — flag `print(error)` or `try?` in user-triggered actions.
- Remove unused imports, parameters, and dead code.

---

## Backend (Python/FastAPI) Rules

### Architecture
- FastAPI app with async SQLAlchemy + Alembic for Postgres.
- External integrations: Alpaca Broker API, Plaid API, Redis + ARQ for background jobs.
- Raise domain exceptions (`NotFoundError`, `AuthenticationError`, `AuthorizationError`) — never use `HTTPException` directly.
- Response shape: `{"error": "message", "code": "NOT_FOUND", "detail": {...}}`.

### Testing
- pytest-asyncio with `asyncio_mode = "auto"`.
- External services mocked via `conftest.py` fixtures overriding FastAPI dependencies.
- Unit tests have no DB or network. Integration tests use a real test DB with mocked external services.

### Conventions
- Conventional commits: `<type>(<scope>): <summary>`.
- No multiple Alembic heads — flag migration conflicts.

---

## General Rules
- Only flag real violations in the actually changed code — don't fabricate issues.
- If a rule doesn't apply to the changed files, skip it.
- Prioritize: type safety and correctness first, deprecated API second, style nits last.
- For each violation, provide a concrete fix with a code snippet.
