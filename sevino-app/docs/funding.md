# Plaid + ACH Funding (iOS)

Reference for the iOS side of bank linking. Covers the shipped flow, component layout, state model, LinkKit integration specifics, and deferred items.

The backend counterpart lives at `sevino-api/docs/funding.md`.

---

## What this feature does

From `HomeView`, tapping the `$` button expands a modal (`FundingMorphingView`). If the user has no linked bank, the modal shows a single "Link a bank account" CTA. Tapping it mints a Plaid Link token via the backend, opens the Plaid Link sheet on top of the still-expanded modal, and completes the ACH relationship creation after Plaid returns. When a relationship exists, the modal shows the Deposit / Withdraw row (currently no-op placeholders — wiring is deferred).

Deposit/Withdraw button behavior, transfer history UI, Settings-based unlink, and OAuth-institution support are all deferred to follow-up tickets (see "Deferred" below).

---

## Architecture

MVVM with `@Observable`. Views are thin; state lives on `FundingViewModel`, composed onto `HomeViewModel.funding` so `FundingMorphingView` keeps its single `viewModel: HomeViewModel` parameter.

```
HomeView
  └─ FundingMorphingView (the $ modal)
       .task(id: isExpanded) → viewModel.funding.loadRelationships()
       │
       ├─ error banner (if displayedError)
       ├─ header / stats / details table / info row / disclaimer
       ├─ actionRow:
       │     hasLinkedBank == false → linkBankButton
       │     hasLinkedBank == true  → Deposit + Withdraw (empty closures)
       │
       └─ .sheet(isPresented: isShowingPlaidLink)
            └─ PlaidLinkSheet (UIViewControllerRepresentable over LinkKit)
                  onSuccess → viewModel.funding.onPlaidSuccess(...)
                  onExit    → viewModel.funding.onPlaidExit(error:)
```

## Component layout

| Path | Role |
|---|---|
| `Sevino/Models/Funding/FundingDTOs.swift` | Wire-format types: `LinkTokenResponse`, `LinkBankRequest`, `AchRelationshipDTO`, `AchRelationshipListResponse` (internal decode hop for the wrapped list response). |
| `Sevino/Services/FundingService.swift` | `FundingServiceProtocol` + concrete `FundingService`. Singleton `.shared`, protocol-injectable for tests. Three methods: `createLinkToken`, `linkBank`, `listAchRelationships`. |
| `Sevino/ViewModels/Funding/FundingViewModel.swift` | `@Observable`. Owns relationships, loading state, error state, and Plaid sheet state. |
| `Sevino/ViewModels/Home/HomeViewModel.swift` | Composes `FundingViewModel` as `var funding`. |
| `Sevino/Views/Funding/PlaidLinkSheet.swift` | `UIViewControllerRepresentable` around LinkKit. Retains handler on Coordinator, dispatches `open(...)` on the next runloop. |
| `Sevino/Views/Home/FundingMorphingView.swift` | The `$` modal. Wires `.task(id:)`, `.sheet(isPresented:)`, and the branched action row. Deposit/Withdraw closures remain empty per Locked Decision #1. |
| `SevinoTests/Mocks/MockFundingService.swift` | Test double conforming to `FundingServiceProtocol`. |
| `SevinoTests/FundingViewModelTests.swift` | 16 unit tests covering the VM's contract. |

## State model

`FundingViewModel` is the single source of truth for the feature:

| Property | Type | Role |
|---|---|---|
| `relationships` | `[AchRelationshipDTO]` | Active relationships for the signed-in user. |
| `isLoading` | `Bool` | UI spinner / button-disable signal. |
| `serverError` | `APIError?` | Backend-sourced error decoded by `APIClient`. |
| `localError` | `String?` | Client-side error (Plaid exit with error, unexpected throw). |
| `linkToken` | `String?` | Present only while the Plaid sheet is live. |
| `isShowingPlaidLink` | `Bool` | Binds to `.sheet(isPresented:)`. |

Derived:

| Computed | Role |
|---|---|
| `hasLinkedBank` | `!relationships.isEmpty`. Drives the action-row branch. |
| `displayedError` | `serverError?.localizedDescription ?? localError`. Single string the banner reads. Server errors win over local fallbacks because they're more specific. |

The split between `serverError` and `localError` keeps `APIError` strictly aligned with the backend JSON shape; any non-API-error case (Plaid network blip, LinkKit exit-with-error, unforeseen throw) funnels into `localError` without polluting `APIError`.

## Lifecycle

### Modal expand
`.task(id: isExpanded)` in `expandedContent` fires `loadRelationships()` every time `isExpanded` becomes true. Auto-cancels if the modal collapses mid-fetch — prevents a stale write from racing a user who dismisses the modal before the network returns.

### Link-bank happy path
1. User taps "Link a bank account" → `startBankLink()` clears prior errors, calls `createLinkToken()`, sets `linkToken` and flips `isShowingPlaidLink = true`.
2. SwiftUI presents `PlaidLinkSheet` on top of the still-expanded modal.
3. User completes Plaid auth → `PlaidLinkSheet.onSuccess` fires with metadata from LinkKit.
4. `onPlaidSuccess(...)` calls `FundingService.linkBank(...)`, then `await loadRelationships()`, then sets `isShowingPlaidLink = false`.
5. The `await loadRelationships()` **before** dismissing the sheet is load-bearing: by the time the sheet animates away, `hasLinkedBank == true` and the action row has re-rendered as Deposit/Withdraw. No re-tap of `$` required.

### Exit paths
- User cancels in Plaid (tap X) → `onExit(error: nil)` → silent dismiss, no banner.
- Plaid surfaces a terminal error → `onExit(error: non-nil)` → `localError = "Couldn't connect to your bank. Try again."`
- Backend returns `BANK_ALREADY_LINKED` on re-link attempt → `serverError` populated AND a fresh `loadRelationships()` runs so UI catches up to server state.

## Plaid LinkKit integration

### Handler retention
`Plaid.create(config).get()` returns a `Handler` that LinkKit expects the caller to retain for the duration of the session. Releasing it early makes LinkKit tear down silently before `onSuccess` fires. `PlaidLinkSheet.Coordinator` stores it as `var handler: Handler?` and the SwiftUI context keeps the Coordinator alive for the sheet's lifetime.

### Presentation
`handler.open(presentUsing: .viewController(host))` is dispatched via `DispatchQueue.main.async` so the host view controller is already in the window hierarchy when LinkKit tries to present on top of it. Direct-open races `viewDidAppear` on some iOS versions.

### Metadata trust
Per Locked Decision #4, the values LinkKit hands back in `SuccessMetadata.institution.name` and `accounts[0].{id, mask, name}` are trusted verbatim and sent to the backend as display-only fields. No refetch from `/institutions/get_by_id` or `/accounts/get`.

### Account select
Plaid Dashboard is set to "Account Select: Enabled for one account," so `metadata.accounts` has exactly one element in practice. `PlaidLinkSheet` defensively takes `.first` — treat `nil` as a programmer error.

## Error surface

The inline banner at the top of `expandedContent` reads from `displayedError`:

```swift
if let message = viewModel.funding.displayedError {
    Text(message)
        .font(.system(size: 13 * scale, weight: .medium))
        .foregroundStyle(Color.sevinoNegative)
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10 * scale)
        .padding(.horizontal, 12 * scale)
        .background(Color.sevinoNegative.opacity(0.12), in: .rect(cornerRadius: 12 * scale))
        .transition(.opacity)
}
```

- `ACCOUNT_NOT_ACTIVE`, `BANK_ALREADY_LINKED`, `ALPACA_ERROR` etc. arrive as `APIError` → surface as `serverError.localizedDescription`.
- Plaid exit with non-nil error → `localError`.
- Plaid user-cancel (`error == nil`) → silent.
- `BANK_ALREADY_LINKED` triggers a fresh `loadRelationships()` so the UI picks up the server's existing link.

## Wire format + APIClient

All funding requests go through `APIClient.shared`:

- JWT is auto-attached via `tokenProvider` (defaults to `AuthService.shared.accessToken`)
- `X-API-Key` header attached when `AppConfig.apiKey` is non-empty
- JSON keys convert camelCase ↔ snake_case automatically — no manual `CodingKeys` on DTOs
- Non-2xx responses decode to `APIError` and throw

The only mild wrinkle: the backend's `GET /v1/funding/ach-relationships` returns `{"relationships": [...]}` rather than a bare array (for future-extensibility). `FundingService.listAchRelationships()` decodes the wrapper and returns the unwrapped `[AchRelationshipDTO]` to callers — the wrapper type is an internal hop, invisible to the view model and tests.

For body-less POST calls (the `/link-token` endpoint takes no request body), `FundingService` uses a private `EmptyBody: Encodable` sentinel that serializes to `{}`.

## Testing

Protocol DI via `FundingServiceProtocol`. `MockFundingService` (under `SevinoTests/Mocks/`, alongside `MockAPIClient` and `MockAuthService`) provides per-method `Result`-based stubbing and call tracking.

`FundingViewModelTests` covers 16 scenarios:

- Load relationships: populated, empty, API failure → `serverError`
- Start bank link: happy path, API failure, non-API error fallback, clears pre-existing errors
- Plaid success: happy path refreshes-then-dismisses, `BANK_ALREADY_LINKED` still refreshes, unrelated API error dismisses without refresh, non-API error fallback
- Plaid exit: silent on nil, local error on non-nil
- Error coalescing: server wins over local, local-only works, `clearErrors` resets both

All tests run on `@MainActor` matching the project default (`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`). No UI tests for `FundingMorphingView` / `PlaidLinkSheet` — LinkKit is glued through a representable with no business logic; covered by manual sandbox E2E.

## Swift concurrency

Project sets `SWIFT_APPROACHABLE_CONCURRENCY = YES` with `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. All view models and views are implicitly `@MainActor`. The `FundingService.Protocol` methods are `async throws` and the concrete service delegates to `APIClient`, which already hops off main for network work inside URLSession.

Strict-concurrency (`SWIFT_STRICT_CONCURRENCY=complete`) produces **zero warnings** on any funding file — verified. The branch is ready for a future project-wide Swift 6 strict-mode migration.

## Deferred / known gaps

Tracked in Linear under the **Alpaca — Bank Linking & Transfers (+Plaid)** project:

- **SEV-222** — Plaid OAuth institutions (TD, Chase, BofA, etc.). Requires a registered redirect URI, AASA file hosted at an HTTPS domain, `Associated Domains` entitlement (`applinks:<domain>`), and a `.onOpenURL` handler that resumes LinkKit via `LinkTokenConfiguration.receivedRedirectUri`. Blocker for any real-user launch that links a major U.S. bank.
- **SEV-223 (Shivam)** / **SEV-227 (Tharsihan)** — Build the deposit/withdraw views, then wire them to the backend `POST /v1/funding/transfers` endpoint. Deposit/Withdraw buttons currently have empty `action: {}` closures per Locked Decision #1. When wiring, set `isSubmitting = true` at the start of the action and `false` in a `defer` to prevent double-submits via button-disable.
- **SEV-224 (Shivam)** / **SEV-228 (Tharsihan)** — Transfer history views + wiring to `GET /v1/funding/transfers`.
- **SEV-225** — `ITEM_LOGIN_REQUIRED` re-auth. Needs a backend webhook listener (deferred) + an endpoint to mint update-mode link tokens + iOS surfacing a reconnect CTA + reusing `PlaidLinkSheet` in update mode.
- **SEV-226** — Settings entry point for listing linked banks, unlinking, and editing nicknames. `LinkBankRequest.nickname` is already plumbed; currently always sent as `nil`.

Style items acknowledged and deferred as polish:

- Hardcoded `"Link a bank account"` CTA text and `localError` copy are not yet routed through `L10n`. The plan intentionally hardcoded these to keep Phase 5 scope tight; a polish ticket would migrate them.
- `FundingViewModel` exposes non-`private(set)` state so tests can seed it directly. Acceptable trade-off for MVVM testability.
- `FundingMorphingView` keeps the computed-property style (`expandedContent`, `actionRow`, etc.) rather than extracting subview structs. Pre-existing pattern across the home feature.
- Error banner uses `.transition(.opacity)` without a paired `.animation(_:value:)` — accepted nit.
