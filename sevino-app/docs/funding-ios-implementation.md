# iOS Funding UI — Phased Implementation Plan

> Companion to `sevino-app/docs/funding-ios-research.md` (state of the iOS
> codebase — the single source of truth for "what exists"). Scope + UX
> decisions are locked by the approved plan-mode doc and summarized in the
> "Locked Decisions" section below.
>
> Branch: `tharsihanariyanayagam/plaid-ach-funding` (shared with the backend).
>
> Audience: the implementer. Open Phase 0 and work top-to-bottom. Each phase
> ends in a compilable + runnable state — you can pause after any phase, run
> the verification, and come back later without half-built code in the tree.
>
> Paired style with `sevino-api/docs/plaid-ach-funding-implementation.md`.

---

## Locked Decisions

Carried forward from the approved plan-mode session. Do not re-litigate.

1. **Scope — bank-link flow only.** Deposit/Withdraw backend wiring, transfer
   history, `ITEM_LOGIN_REQUIRED` re-auth, and a Settings entry point are all
   explicitly out of scope. The two existing Deposit/Withdraw buttons in
   `FundingMorphingView.swift:134` and `:141` keep their empty `action: {}`
   closures.
2. **CTA shape.** When `hasLinkedBank == false`, a single full-width "Link a
   bank account" button replaces the Deposit/Withdraw row. Everything else in
   the expanded modal (balance, APY badge, stat cards, details table, info
   row, disclaimer) stays visible in both branches.
3. **Post-Plaid UX — no re-tap of `$`.** The Plaid sheet is attached inside
   `FundingMorphingView`'s `expandedContent`, so it layers on top of the still-
   expanded modal. `onPlaidSuccess` awaits `loadRelationships()` *before*
   flipping `isShowingPlaidLink = false`, so when the sheet dismisses the
   action row has already re-rendered as Deposit/Withdraw.
4. **Institution metadata origin.** Mirror the backend: trust the values
   LinkKit hands back in `onSuccess` metadata (`institution.name`,
   `accounts[0].{id, mask, name}`). No fallbacks, no server refetch.
5. **Nickname.** User-editable nickname is deferred. Send `nickname = nil`
   on `/link-bank` for this PR.
6. **File placement.** Per `Sevino/CLAUDE.md` — Views under
   `Views/<Feature>/`, ViewModels under `ViewModels/<Feature>/`, Services at
   the top of `Services/`, Models under `Models/<Feature>/`. Unit tests in
   `SevinoTests/`.
7. **Swift concurrency conventions.** Project default is
   `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`; view models inherit it. No
   explicit `@MainActor` on new types unless opting a specific method to
   `nonisolated`.
8. **Lifecycle hook for `loadRelationships()` on expand.**
   `.task(id: isExpanded) { if isExpanded { await loadRelationships() } }`
   inside `expandedContent`. Auto-cancels if the modal collapses mid-fetch —
   prevents stale writes from racing a user who taps outside before the
   network returns.
9. **Error surface — inline banner.** A conditional `Text` at the top of
   `expandedContent` bound to `viewModel.funding.displayedError`. Not
   `.alert(item:)` — the errors in scope are recoverable (retry Plaid, pick
   a different bank), so a modal dialog would feel heavy-handed.
10. **Error model — coalesce locally, don't pollute `APIError`.**
    `FundingViewModel` exposes a computed `displayedError: String?` backed by
    two stored properties: `serverError: APIError?` (backend-sourced,
    decoded by `APIClient`) and `localError: String?` (anything client-side
    — Plaid-exit errors, unexpected throws, future offline checks). Keeps
    `APIError` strictly aligned with the backend JSON shape and lets the
    banner bind to one property.
11. **Phase 0 path — Xcode UI (Path A).** Project → `Sevino` target →
    General → Frameworks picker. Safer pbxproj diff than hand-editing the
    file. Path B (direct edit) is documented in Phase 0 as a backup only.
12. **Test doubles live under `SevinoTests/Mocks/`.** Convention already
    established by `MockAPIClient.swift` and `MockAuthService.swift` in that
    folder. `MockFundingService.swift` joins them.

---

## Phase 0 — Link LinkKit to the Sevino App Target

**Goal:** Make `import LinkKit` compile in the Sevino app target. Today the
`plaid-link-ios` package is declared in `project.pbxproj:212` and resolved in
`Package.resolved:5-11` (v6.4.7), but no `XCSwiftPackageProductDependency`
entry wires it to the Sevino target — see `funding-ios-research.md` §
"Plaid LinkKit SDK — the caveat". Until this is fixed, nothing in Phase 4
(or anything that imports LinkKit) will build.

This is a tree-state-only change: no Swift files are added or modified here,
but the tree stays compilable afterwards because the broken `import LinkKit`
is introduced in Phase 4, not now.

**Files modified:**

- `Sevino.xcodeproj/project.pbxproj` — add 1 new entry in each of:
  - `PBXBuildFile` section (mirroring the Supabase entry at line 10)
  - `PBXFrameworksBuildPhase` for the Sevino target (line 62 list)
  - Sevino native target's `packageProductDependencies` (line 126 list)
  - `XCSwiftPackageProductDependency` section (line 762 shape)

No other files touched. `Package.resolved` stays as-is — the package is
already resolved, we're only linking the product.

**Use Path A (Xcode UI).** Locked Decision #11. Path B is documented as a
backup for scripting scenarios; do not use it unless the Xcode picker
misbehaves.

*Path A — Xcode UI:*

1. Open `Sevino.xcodeproj` in Xcode 16+.
2. Select the project node → the `Sevino` target → **General** tab.
3. Under **Frameworks, Libraries, and Embedded Content**, click `+`.
4. In the picker, expand `plaid-link-ios` and select `LinkKit`.
5. Leave **Embed** set to "Do Not Embed" (LinkKit is a dynamic framework
   vended by the package; the default the picker chooses is correct).
6. Save. Confirm Xcode has edited `project.pbxproj` — git diff should show
   exactly the four sections above gaining a `LinkKit` entry keyed by fresh
   24-char hex UUIDs.

*Path B — direct pbxproj edit (use if you're scripting the commit or the
Xcode picker misbehaves):*

Generate two fresh 24-char hex UUIDs (any hex generator; Xcode itself uses
random hex). Call them `<BUILD_UUID>` and `<PRODUCT_UUID>`. Reference the
existing package object `C4E361A42F7779AE0091BEA9`. Insert:

```
# PBXBuildFile section (near line 10)
<BUILD_UUID> /* LinkKit in Frameworks */ = {isa = PBXBuildFile; productRef = <PRODUCT_UUID> /* LinkKit */; };

# PBXFrameworksBuildPhase, Sevino target (line 62 list)
<BUILD_UUID> /* LinkKit in Frameworks */,

# Sevino native target → packageProductDependencies (line 126 list)
<PRODUCT_UUID> /* LinkKit */,

# XCSwiftPackageProductDependency section (line 762 shape)
<PRODUCT_UUID> /* LinkKit */ = {
    isa = XCSwiftPackageProductDependency;
    package = C4E361A42F7779AE0091BEA9 /* XCRemoteSwiftPackageReference "plaid-link-ios" */;
    productName = LinkKit;
};
```

**Dependencies:** none.

**Verification:**

```bash
# 1) Project still opens and parses cleanly:
xcodebuild -project sevino-app/Sevino.xcodeproj -list
# Expect: Sevino target listed, no parse error.

# 2) App target builds cleanly with no Swift code changes yet:
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED. No "no such module 'LinkKit'" error possible
# yet (no file imports it), but confirm nothing regressed.

# 3) Quick sanity — LinkKit is now in the target:
grep -c "LinkKit" Sevino.xcodeproj/project.pbxproj
# Expect: 4 (one per section above). Before this phase the count was 0.
```

**Done looks like:** `project.pbxproj` has 4 new `LinkKit` references,
`xcodebuild build` on the Sevino scheme succeeds, running the app in the
simulator still lands on the existing authed HomeView with no behavioral
change. Commit as `chore(funding): link LinkKit to Sevino target`.

---

## Phase 1 — Codable DTOs

**Goal:** Wire-format types for the three backend endpoints, matching the
shapes documented in `funding-ios-research.md` § "Backend endpoints this
feature consumes". `APIClient`'s encoder/decoder already handles snake ↔
camel conversion, so Swift field names stay camelCase with no explicit
`CodingKeys` needed.

**Files created:**

- `Sevino/Models/Funding/FundingDTOs.swift`

**Files modified:** none.

**Skeleton — `FundingDTOs.swift`:**

```swift
import Foundation

/// Response from POST /v1/funding/link-token.
struct LinkTokenResponse: Decodable {
    let linkToken: String
}

/// Body for POST /v1/funding/link-bank.
/// Field names match the backend schema in app/schemas/funding.py.
struct LinkBankRequest: Encodable {
    let publicToken: String
    let accountId: String
    let institutionName: String?
    let accountMask: String?
    let accountName: String?
    let nickname: String?
}

/// Response for POST /v1/funding/link-bank and entries in
/// GET /v1/funding/ach-relationships.
struct AchRelationshipDTO: Decodable, Identifiable, Equatable {
    let id: UUID
    let alpacaRelationshipId: String
    let institutionName: String?
    let accountMask: String?
    let accountType: String?
    let nickname: String?
    let status: String
}
```

**Dependencies:** Phase 0 (target builds).

**Verification:**

```bash
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED. The DTOs are un-referenced but compile.
```

**Done looks like:** `FundingDTOs.swift` exists, builds, and is not yet
referenced by any other file. App behavior unchanged. The three placeholder
files still exist untouched.

---

## Phase 2 — FundingService Protocol + Implementation

**Goal:** Thin async wrapper over `APIClient` for the three endpoints. Mirrors
the shape of `OnboardingService` (`Services/OnboardingService.swift:4-31`) —
protocol for DI/testability, singleton `.shared` for production use.

**Files created:**

- `Sevino/Services/FundingService.swift`

**Files modified:** none.

**Skeleton — `FundingService.swift`:**

```swift
import Foundation

/// DI protocol. Unit tests substitute a MockFundingService (Phase 7).
protocol FundingServiceProtocol {
    func createLinkToken() async throws -> String
    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO
    func listAchRelationships() async throws -> [AchRelationshipDTO]
}

final class FundingService: FundingServiceProtocol {
    static let shared = FundingService()

    private let api: APIClientProtocol

    init(api: APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func createLinkToken() async throws -> String {
        let response: LinkTokenResponse = try await api.post(
            "/v1/funding/link-token",
            body: EmptyBody() // or nil-body variant matching APIClient's shape
        )
        return response.linkToken
    }

    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO {
        try await api.post("/v1/funding/link-bank", body: request)
    }

    func listAchRelationships() async throws -> [AchRelationshipDTO] {
        try await api.get("/v1/funding/ach-relationships")
    }
}
```

Implementation notes:

- Match `OnboardingService`'s exact method-shape for the `api.post` /
  `api.get` calls. If `APIClient` doesn't currently expose a body-less `post`
  overload, add one in this file (not in `APIClient.swift`) as an extension,
  or pass `EmptyBody: Encodable {}` — choose whichever pattern
  `OnboardingService` is already using.
- `createTransfer` / `list_transfers` / `delete` endpoints are intentionally
  omitted — scope lock #1.

**Dependencies:** Phase 1 (DTOs exist).

**Verification:**

```bash
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED. Service is un-referenced but compiles.
```

**Done looks like:** `FundingService.swift` compiles; `FundingService.shared`
can be referenced from a Swift REPL / test without runtime error; no UI or
view model references it yet. App behavior unchanged.

---

## Phase 3 — FundingViewModel + Compose into HomeViewModel

**Goal:** The observable state holder for the feature. Owns relationships,
loading state, errors, and the two pieces of Plaid UI state. Composed onto
`HomeViewModel` as `let funding = FundingViewModel()` so `FundingMorphingView`
keeps its single `viewModel: HomeViewModel` parameter.

**Files created:**

- `Sevino/ViewModels/Funding/FundingViewModel.swift`

**Files modified:**

- `Sevino/ViewModels/Home/HomeViewModel.swift` — add one stored property,
  nothing else.

**Skeleton — `FundingViewModel.swift`:**

```swift
import Foundation
import Observation

@Observable
final class FundingViewModel {

    // Network state
    var relationships: [AchRelationshipDTO] = []
    var isLoading: Bool = false

    // Error state — see Locked Decision #10.
    // `serverError` carries backend-decoded APIError; `localError` carries any
    // client-side error (Plaid exit, unexpected throw, future offline checks).
    // Views bind to `displayedError` — a single coalesced string.
    var serverError: APIError?
    var localError: String?

    // Plaid sheet state (driven into PlaidLinkSheet in Phase 4)
    var linkToken: String?
    var isShowingPlaidLink: Bool = false

    private let service: FundingServiceProtocol

    init(service: FundingServiceProtocol = FundingService.shared) {
        self.service = service
    }

    /// Source of truth for the CTA branch in FundingMorphingView.
    var hasLinkedBank: Bool { !relationships.isEmpty }

    /// What the inline banner renders. Server error wins if both are set
    /// (server errors are more specific / actionable than local fallbacks).
    var displayedError: String? {
        serverError?.localizedDescription ?? localError
    }

    /// Clear both error sources — call at the start of any operation that
    /// should reset the banner (e.g. re-tapping "Link a bank account").
    func clearErrors() {
        serverError = nil
        localError = nil
    }

    /// Called when the $ modal expands (Phase 5 wires `.task(id: isExpanded)`).
    func loadRelationships() async {
        isLoading = true
        defer { isLoading = false }
        do {
            relationships = try await service.listAchRelationships()
        } catch let apiError as APIError {
            serverError = apiError
        } catch {
            localError = "Something went wrong. Try again."
        }
    }

    /// Called when the user taps "Link a bank account".
    func startBankLink() async {
        clearErrors()
        isLoading = true
        defer { isLoading = false }
        do {
            linkToken = try await service.createLinkToken()
            isShowingPlaidLink = true
        } catch let apiError as APIError {
            serverError = apiError
        } catch {
            localError = "Something went wrong. Try again."
        }
    }

    /// Called from PlaidLinkSheet's onSuccess closure in Phase 5.
    /// NOTE: awaits loadRelationships BEFORE flipping isShowingPlaidLink = false
    /// so the action row has already re-rendered by the time the sheet animates
    /// away. This is what makes the "no re-tap of $" UX (Decision #3) work.
    func onPlaidSuccess(
        publicToken: String,
        accountId: String,
        institutionName: String?,
        accountMask: String?,
        accountName: String?
    ) async {
        do {
            _ = try await service.linkBank(
                LinkBankRequest(
                    publicToken: publicToken,
                    accountId: accountId,
                    institutionName: institutionName,
                    accountMask: accountMask,
                    accountName: accountName,
                    nickname: nil
                )
            )
            await loadRelationships()
        } catch let apiError as APIError {
            serverError = apiError
            // On BANK_ALREADY_LINKED specifically, still refresh so UI catches up.
            if apiError.code == "BANK_ALREADY_LINKED" {
                await loadRelationships()
            }
        } catch {
            localError = "Something went wrong. Try again."
        }
        linkToken = nil
        isShowingPlaidLink = false
    }

    /// Called from PlaidLinkSheet's onExit closure in Phase 5.
    /// nil error = user-cancelled — silent. Non-nil = surface generic banner.
    func onPlaidExit(error plaidError: Error?) {
        if plaidError != nil {
            localError = "Couldn't connect to your bank. Try again."
        }
        linkToken = nil
        isShowingPlaidLink = false
    }
}
```

**Skeleton — `HomeViewModel.swift` diff:**

```swift
@Observable
final class HomeViewModel {
    // ... existing mock funding data (cashBalance, cashApy, etc., lines 12-22) ...

    let funding = FundingViewModel()   // NEW — composes the feature view model
}
```

Implementation notes:

- `APIError` itself is NOT edited in this PR — see Locked Decision #10.
  Local errors are plain `String` values on `localError`; the
  `displayedError` computed property coalesces them with decoded
  `serverError` for the banner to read.
- `hasLinkedBank` and `displayedError` are computed properties on top of
  stored state; `@Observable` re-derives them automatically — no
  `@ObservationIgnored` needed.
- Kept on `@MainActor` by project default (see Locked Decision #7); all
  `async` network calls hop off the main thread inside `APIClient`.

**Dependencies:** Phases 1 + 2.

**Verification:**

```bash
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED.

# Run the app on simulator: behavior unchanged from prior phases.
# The $ modal still shows the old Deposit/Withdraw row (wiring comes in Phase 5).
```

**Done looks like:** `FundingViewModel.swift` compiles and is reachable from
`HomeViewModel.funding`. `FundingMorphingView` still uses the old
`actionButtons` — no UI changes yet. Running the app and tapping `$` shows
exactly what shipped before.

---

## Phase 4 — PlaidLinkSheet (UIViewControllerRepresentable around LinkKit)

**Goal:** A SwiftUI-presentable wrapper over LinkKit's UIKit
`PLKHandler` / `LinkTokenConfiguration`. This is the first file that
`import LinkKit`s — Phase 0 ensures it compiles.

**Files created:**

- `Sevino/Views/Funding/PlaidLinkSheet.swift`

**Files modified:** none.

**Skeleton — `PlaidLinkSheet.swift`:**

```swift
import LinkKit
import SwiftUI
import UIKit

/// Wraps Plaid LinkKit in a SwiftUI sheet.
/// Constructed fresh each time isShowingPlaidLink flips true (see Phase 5).
struct PlaidLinkSheet: UIViewControllerRepresentable {

    let linkToken: String
    let onSuccess: (
        _ publicToken: String,
        _ accountId: String,
        _ institutionName: String?,
        _ accountMask: String?,
        _ accountName: String?
    ) -> Void
    let onExit: (_ error: Error?) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onSuccess: onSuccess, onExit: onExit)
    }

    func makeUIViewController(context: Context) -> UIViewController {
        let host = UIViewController()
        host.view.backgroundColor = .clear

        var config = LinkTokenConfiguration(token: linkToken) { success in
            let meta = success.metadata
            let institutionName = meta.institution.name
            let firstAccount = meta.accounts.first
            context.coordinator.onSuccess(
                success.publicToken,
                firstAccount?.id ?? "",
                institutionName,
                firstAccount?.mask,
                firstAccount?.name
            )
        }
        config.onExit = { exit in
            context.coordinator.onExit(exit.error)
        }

        do {
            let handler = try Plaid.create(config).get()
            context.coordinator.handler = handler  // retain — handler goes away otherwise
            DispatchQueue.main.async {
                handler.open(presentUsing: .viewController(host))
            }
        } catch {
            DispatchQueue.main.async {
                context.coordinator.onExit(error)
            }
        }

        return host
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {}

    final class Coordinator {
        var handler: Handler?
        let onSuccess: (String, String, String?, String?, String?) -> Void
        let onExit: (Error?) -> Void

        init(
            onSuccess: @escaping (String, String, String?, String?, String?) -> Void,
            onExit: @escaping (Error?) -> Void
        ) {
            self.onSuccess = onSuccess
            self.onExit = onExit
        }
    }
}
```

Implementation notes:

- LinkKit's Plaid Dashboard is configured for "Account Select: one account"
  (per `sevino-api/docs/plaid-integration.md:39`), so `meta.accounts` has
  exactly one element. `.first` is a defensive access; treat nil as a
  programmer error (Plaid should never deliver an empty array under this
  config). If you want to be louder, `assertionFailure` in that branch.
- `handler` MUST be retained through the lifetime of the sheet, or LinkKit
  silently tears down before onSuccess fires. Storing it on the Coordinator
  is the canonical fix.
- Presenting `handler.open` is dispatched async to next runloop so the
  host view controller is already in the window hierarchy — direct-open
  races `viewDidAppear` on some iOS versions.
- This file makes no network calls itself. `createLinkToken` already ran in
  the view model before this view is constructed.

**Dependencies:** Phase 0 (LinkKit linked to target). Does NOT depend on
Phase 3 — the view takes callbacks, not a view model reference.

**Verification:**

```bash
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED. The "no such module 'LinkKit'" failure this phase
# would produce is exactly what Phase 0 prevented.

# Run the app on simulator: behavior unchanged. Nothing presents the sheet yet.
```

**Done looks like:** `PlaidLinkSheet.swift` compiles against LinkKit.
Nothing presents it yet (Phase 5). App behavior unchanged.

---

## Phase 5 — Wire FundingMorphingView to Real State

**Goal:** Replace the empty `actionButtons` with a branch on `hasLinkedBank`,
attach the Plaid sheet inside `expandedContent`, and trigger
`loadRelationships()` when the modal expands. This is the phase that lights
the feature up.

**Files modified:**

- `Sevino/Views/Home/FundingMorphingView.swift`

**Files created:** none.

**Skeleton — relevant changes only (surrounding code unchanged):**

```swift
struct FundingMorphingView: View {
    @Bindable var viewModel: HomeViewModel
    let isExpanded: Bool
    // ... existing props

    var body: some View {
        // existing pill-vs-expanded branching ...
    }

    private var expandedContent: some View {
        VStack(spacing: ...) {
            // NEW — inline error banner at top (Locked Decision #9).
            // Reads from the coalesced `displayedError` so one view handles
            // both server-sourced and local errors.
            if let message = viewModel.funding.displayedError {
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoNegative)
                    .padding(.horizontal)
                    .transition(.opacity)
            }

            // existing: header + APY badge + stat cards + details table + infoRow + disclaimer ...

            actionRow   // was `actionButtons`, now branched

            // existing: disclaimer ...
        }
        // Refresh relationships each time the modal transitions to expanded.
        // Locked Decision #8 — `.task(id:)` auto-cancels if the modal collapses
        // mid-fetch, preventing stale writes.
        .task(id: isExpanded) {
            if isExpanded {
                await viewModel.funding.loadRelationships()
            }
        }
        // Plaid sheet layered on top. Modal remains expanded underneath — this is
        // the core mechanic for Decision #3 (no re-tap of $ after Plaid).
        .sheet(isPresented: $viewModel.funding.isShowingPlaidLink) {
            if let token = viewModel.funding.linkToken {
                PlaidLinkSheet(
                    linkToken: token,
                    onSuccess: { publicToken, accountId, institutionName, accountMask, accountName in
                        Task {
                            await viewModel.funding.onPlaidSuccess(
                                publicToken: publicToken,
                                accountId: accountId,
                                institutionName: institutionName,
                                accountMask: accountMask,
                                accountName: accountName
                            )
                        }
                    },
                    onExit: { error in
                        viewModel.funding.onPlaidExit(error: error)
                    }
                )
            }
        }
    }

    @ViewBuilder
    private var actionRow: some View {
        if viewModel.funding.hasLinkedBank {
            // EXISTING two-button row — DO NOT TOUCH the `action: {}` closures.
            // Lifted verbatim from lines 132-148 of the pre-change file.
            HStack(spacing: ...) {
                Button("Deposit", action: {})     // empty — deferred
                // ... existing styling ...
                Button("Withdraw", action: {})    // empty — deferred
                // ... existing styling ...
            }
        } else {
            Button(action: {
                Task { await viewModel.funding.startBankLink() }
            }) {
                Text("Link a bank account")
                    .frame(maxWidth: .infinity)
                    .padding()
                    // match the existing button visual styling — full-width pill,
                    // same corner radius + typography as the Deposit button.
            }
            .disabled(viewModel.funding.isLoading)
        }
    }
}
```

Implementation notes:

- **Do not touch** the existing `action: {}` closures on Deposit/Withdraw.
  Locked Decision #1 — deposit/withdraw UX is a separate thread.
- Stats / APY / details table remain visible in both branches. Only the
  action row itself swaps.
- `@Bindable` unlocks the `$viewModel.funding.isShowingPlaidLink` syntax
  SwiftUI's `.sheet(isPresented:)` needs. If the file is currently plain
  `@State var viewModel`, switch it to `@Bindable` here.
- Error banner reads from `viewModel.funding.displayedError` (Locked
  Decision #10). No direct access to `serverError` or `localError` from
  the view layer.

**Dependencies:** Phases 1–4.

**Verification:**

```bash
cd sevino-api && make infra && make server &
cd ../sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED.

# Manual smoke (any test user WITH a linked bank or freshly seeded):
# 1. Launch app, sign in
# 2. Tap $ on home → modal expands
# 3. If no bank → a single "Link a bank account" button shows
# 4. If bank linked → Deposit + Withdraw row shows
# 5. Close modal, no crashes, no pending sheet
```

**Done looks like:** Tapping `$` on a freshly-seeded no-bank user shows the
single Link CTA; tapping it presents the Plaid sheet (end-to-end Plaid +
backend handshake validated in Phase 8). The placeholder files still exist
in the tree — the plan intentionally defers their removal.

---

## Phase 6 — Delete Placeholder Files

**Goal:** Remove the three `*Placeholder.swift` files identified in
`funding-ios-research.md` § "Placeholder files (to be deleted)". They're
empty TODO comments — deletion is purely cosmetic but keeps grep-ability
honest.

**Files deleted:**

- `Sevino/Views/Funding/FundingPlaceholder.swift`
- `Sevino/ViewModels/Funding/FundingViewModelPlaceholder.swift`
- `Sevino/Models/Funding/FundingModelPlaceholder.swift`

**Files modified:**

- `Sevino.xcodeproj/project.pbxproj` — remove the `PBXBuildFile` +
  `PBXFileReference` + `PBXGroup` children entries for each deleted file. Do
  this via Xcode (right-click → Delete → "Remove References") so the pbxproj
  diff is mechanical, or use `xcodeproj` CLI if scripting.

**Dependencies:** None technically, but pragmatically run after Phase 5 so
you're deleting files the new implementation has clearly replaced (easier
for PR reviewers to reason about).

**Verification:**

```bash
cd sevino-app
xcodebuild \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  build
# Expect: BUILD SUCCEEDED. No "file not found" errors.

# Sanity:
ls Sevino/Views/Funding/ Sevino/ViewModels/Funding/ Sevino/Models/Funding/
# Expect: only the new files we've authored (no *Placeholder.swift).
```

**Done looks like:** Tree no longer contains the three placeholder files
and the target still builds + runs. Commit as
`chore(funding): remove placeholder funding files`.

---

## Phase 7 — Unit Tests

**Goal:** XCTest coverage for `FundingViewModel` using a `MockFundingService`.
Mirrors the backend's Phase 5 test suite — same scenarios, same edge cases,
just from the client side.

**Files created:**

- `SevinoTests/FundingViewModelTests.swift`
- `SevinoTests/Mocks/MockFundingService.swift`

**Files modified:** none.

**Skeleton — `MockFundingService.swift`:**

```swift
import Foundation
@testable import Sevino

final class MockFundingService: FundingServiceProtocol {

    // Per-method stubbing — assign .success(...) or .failure(...) per test.
    var createLinkTokenResult: Result<String, Error> = .success("link-sandbox-test")
    var linkBankResult: Result<AchRelationshipDTO, Error>?
    var listAchRelationshipsResult: Result<[AchRelationshipDTO], Error> = .success([])

    // Call-count tracking for verifying effects (e.g. "relationships refreshed after success").
    private(set) var createLinkTokenCalls = 0
    private(set) var linkBankCalls: [LinkBankRequest] = []
    private(set) var listAchRelationshipsCalls = 0

    func createLinkToken() async throws -> String {
        createLinkTokenCalls += 1
        return try createLinkTokenResult.get()
    }

    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO {
        linkBankCalls.append(request)
        guard let result = linkBankResult else {
            fatalError("linkBank called but no result stubbed")
        }
        return try result.get()
    }

    func listAchRelationships() async throws -> [AchRelationshipDTO] {
        listAchRelationshipsCalls += 1
        return try listAchRelationshipsResult.get()
    }
}
```

**Skeleton — `FundingViewModelTests.swift`:**

```swift
import XCTest
@testable import Sevino

@MainActor
final class FundingViewModelTests: XCTestCase {

    private func makeSUT(mock: MockFundingService = .init()) -> (FundingViewModel, MockFundingService) {
        let vm = FundingViewModel(service: mock)
        return (vm, mock)
    }

    func test_loadRelationships_populatesRelationshipsAndFlipsHasLinkedBank() async { ... }

    func test_loadRelationships_whenEmpty_hasLinkedBankIsFalse() async { ... }

    func test_startBankLink_setsTokenAndShowsSheet() async { ... }

    func test_startBankLink_whenApiFails_storesServerErrorAndDoesNotShowSheet() async { ... }

    func test_startBankLink_whenNonAPIErrorThrown_storesLocalErrorFallback() async {
        // service throws a non-APIError → `localError` populated with generic copy,
        // `serverError` stays nil, `displayedError` reflects the localError.
    }

    func test_onPlaidSuccess_happyPath_refreshesRelationshipsAndDismissesSheet() async { ... }

    func test_onPlaidSuccess_withBankAlreadyLinked409_storesServerErrorAndStillRefreshes() async { ... }

    func test_onPlaidSuccess_withAccountNotActive409_storesServerErrorAndDismisses() async { ... }

    func test_onPlaidExit_withNilError_isSilent() async {
        // neither serverError nor localError set; displayedError == nil.
    }

    func test_onPlaidExit_withNonNilError_storesLocalErrorCopy() async {
        // localError == "Couldn't connect to your bank. Try again."
        // serverError stays nil.
    }

    func test_displayedError_prefersServerErrorOverLocalError() async {
        // Set both; assert displayedError == serverError's message.
    }

    func test_startBankLink_clearsPreExistingErrors() async {
        // Set serverError + localError, call startBankLink happy-path,
        // assert both cleared before the token is fetched.
    }

    // Note: no explicit ordering test for "loadRelationships before sheet
    // dismiss" — Swift's sequential-await semantics guarantees it structurally
    // (Locked Decision per Q6). The happy-path test verifies both effects
    // happened; Phase 8 E2E verifies it visually.
}
```

Implementation notes:

- Tests run on `@MainActor` so `@Observable` state reads/writes don't cross
  isolation boundaries. Matches the view-model default in the app.
- Build `AchRelationshipDTO` fixtures in a helper extension near the bottom
  of the test file — keep the test method bodies focused on assertions.
- For the "refreshes before dismissing" ordering test, the simplest check is
  to assert `mock.listAchRelationshipsCalls == 1` on the final `await`
  continuation — because `onPlaidSuccess` awaits `loadRelationships()` before
  setting `isShowingPlaidLink = false`, by the time the method returns both
  effects have happened.
- No need to unit-test `PlaidLinkSheet` — LinkKit is glued through a
  representable wrapper with no business logic. Covered by Phase 8 E2E.

**Dependencies:** Phases 1–3.

**Verification:**

```bash
cd sevino-app
xcodebuild test \
  -project Sevino.xcodeproj \
  -scheme Sevino \
  -destination 'platform=iOS Simulator,name=iPhone 15'
# Expect: all FundingViewModelTests pass, zero pre-existing test regressions.
```

**Done looks like:** All tests green on the iPhone 15 simulator. No pre-
existing tests broken.

---

## Phase 8 — Manual Sandbox E2E Verification

**Goal:** Drive the full flow end-to-end against the live backend on the
`tharsihanariyanayagam/plaid-ach-funding` branch with real Plaid + Alpaca
sandbox calls. Piggy-backs on the backend's seeder script so we're testing
against the exact same fixture the backend smoke uses.

**Files modified:** none (verification-only phase).

**Dependencies:** Phases 0–6 merged / applied locally. Phase 7 green.

**Preconditions:**

- Backend checked out on `tharsihanariyanayagam/plaid-ach-funding`, local
  `.env` has real Plaid sandbox credentials + Alpaca sandbox keys + a valid
  `PLAID_FERNET_KEY`.
- iOS app pointed at `http://localhost:8000` (check `AppConfig.baseURL`).
- `X-API-Key` in the iOS app matches the backend's `API_KEY`.
- Supabase local running (`make infra`) with an `auth.users` row for
  `funding-smoke@sevino.test`. The seeder creates it if missing.

**Script:**

```bash
# 1) Backend up
cd sevino-api
make infra
make migrate
make server &
SERVER_PID=$!
sleep 3

# 2) Seed the smoke user with an ACTIVE brokerage + soft-cancel any prior
#    local ACH rows so the app boots into the "no bank" branch.
uv run python scripts/seed_funding_sandbox.py
# The script prints the user's email + password — note them for step 4.

# 3) Run the iOS app on simulator
cd ../sevino-app
open Sevino.xcodeproj
# Cmd+R in Xcode → iPhone 15 simulator

# 4) Manual flow
# - Sign in as funding-smoke@sevino.test with the seeder-printed password.
# - Tap the $ button on Home.
#   EXPECT: modal expands → balance/APY/stats visible → single full-width
#   "Link a bank account" button (no Deposit/Withdraw row).
# - Tap "Link a bank account".
#   EXPECT: Plaid Link sheet slides up. Modal stays expanded underneath.
# - Pick "First Platypus Bank" (sandbox institution).
#   Credentials: user_good / pass_good.
#   Pick any account when the selector appears.
# - Plaid confirms "Success".
#   EXPECT: Plaid sheet dismisses. Modal is STILL EXPANDED (not collapsed).
#   EXPECT: the action row has flipped to show Deposit + Withdraw buttons.
#   EXPECT: tapping Deposit or Withdraw does nothing — empty closures
#   preserved per Locked Decision #1.
# - Tap outside the modal to collapse it, then tap $ again.
#   EXPECT: modal re-opens with Deposit/Withdraw row still visible — the
#   relationship persisted.

# 5) Verify server-side state
curl -s http://localhost:8000/v1/funding/ach-relationships \
  -H "X-API-Key: $API_KEY" \
  -H "Authorization: Bearer $JWT_FOR_SMOKE_USER" | python3 -m json.tool
# EXPECT: one entry; status in {QUEUED, APPROVED}.

# 6) Error-branch smoke: tap "Link a bank account" AGAIN (re-run Plaid).
#    The backend will return BANK_ALREADY_LINKED.
#    EXPECT: inline error banner "This bank is already linked.".
#    EXPECT: relationships list auto-refreshes (still exactly one entry).

# 7) Plaid-exit branch: relaunch, open $, tap Link, then tap Cancel/X
#    inside the Plaid sheet.
#    EXPECT: silent dismiss (user-cancel → no banner).
#    Force-stop Plaid on an error (disconnect simulator internet mid-flow).
#    EXPECT: "Couldn't connect to your bank. Try again." banner.

# 8) Re-run the backend smoke against the same DB — confirms the iOS client
#    and the script share surface area.
cd ../sevino-api
bash scripts/funding_smoke.sh
# EXPECT: passes up to the /link-bank step, then fails there with
# BANK_ALREADY_LINKED — which is exactly the iOS error branch we just saw.

# 9) Shut down
kill $SERVER_PID
```

**Done looks like:**

- Every `EXPECT:` line above matches observed UI or response.
- `$` button never needs a re-tap after a successful link (Decision #3
  validated visually).
- `action: {}` closures on Deposit/Withdraw remain empty (tapping is a
  no-op — Decision #1 validated).
- `uv run alembic heads` on the backend still shows one head.
- No Swift crashes in the Xcode console; no unexpected `APIError.code`
  values surfaced to the banner.

---

## Branch Acceptance Checklist

Before opening the PR for review:

- [ ] `xcodebuild build` on the Sevino scheme succeeds for every commit on
      the branch (each phase ends compilable, per the per-phase Verification
      sections).
- [ ] `xcodebuild test` on the Sevino scheme passes; `FundingViewModelTests`
      included.
- [ ] `project.pbxproj` references `LinkKit` in all 4 sections (Phase 0
      sanity).
- [ ] Three placeholder files are gone; `grep -rn "FundingPlaceholder"` on
      `Sevino/` returns nothing.
- [ ] Deposit/Withdraw buttons in `FundingMorphingView.swift` retain
      `action: {}` empty closures — verified by inspection.
- [ ] Phase 8 manual E2E completed and the result noted in the PR body.
- [ ] PR description lists deferred items (deposit/withdraw wiring, transfer
      history, re-auth, Settings entry point) as NOT in this branch.

---

## Resolved Decisions (previously open questions)

All six open questions from the initial draft have been resolved with
`@tharsihan`. Summarized here so anyone picking up the doc can see how we
got to the Locked Decisions above.

| # | Question | Resolution | Rationale |
|---|---|---|---|
| 1 | Lifecycle hook for `loadRelationships()` on modal expand | `.task(id: isExpanded)` inside `expandedContent` (Locked Decision #8) | Auto-cancels if the modal collapses mid-fetch, preventing stale writes racing a user who taps outside before the network returns |
| 2 | Error banner placement | Inline `Text` banner at top of `expandedContent` (Locked Decision #9) | Errors in scope are recoverable (retry Plaid, different bank); `.alert(item:)` would feel heavy-handed |
| 3 | How to model local (non-server) errors | Computed `displayedError` + `serverError: APIError?` + `localError: String?` (Locked Decision #10) | Keeps `APIError` strictly aligned with the backend JSON shape; scales cleanly as more local error sources get added without `APIError` becoming a grab-bag |
| 4 | Phase 0 path — Xcode UI vs pbxproj edit | Xcode UI (Locked Decision #11) | Safer pbxproj diff; no scripting reason to prefer hand-edit |
| 5 | `MockFundingService` placement | `SevinoTests/Mocks/MockFundingService.swift` (Locked Decision #12) | Convention already established by existing `MockAPIClient.swift` and `MockAuthService.swift` in that folder |
| 6 | Strict ordering test for "no re-tap of $" | Skip — rely on Swift sequential-await + happy-path test + Phase 8 E2E | Method body structurally guarantees order; timestamp-based observation adds complexity without catching a real regression class |
