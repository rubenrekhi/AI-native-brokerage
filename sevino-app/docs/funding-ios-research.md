# iOS Funding UI — Research

> Paired doc to `sevino-api/docs/plaid-ach-funding-plan.md` (what the backend ships) and `sevino-api/docs/plaid-ach-funding-implementation.md` (backend phases).
>
> This doc captures the state of the iOS codebase as it relates to the funding feature, so the implementation plan (next doc) can reference it without re-discovery.
>
> Scope of research: everything needed to take a freshly-onboarded user from "no bank linked" to "bank linked at Alpaca" via a Plaid Link flow launched from the `$` button on the home chat screen.

---

## Feature target (recap)

- User taps the `$` button on home.
- If **no bank linked** → expanded modal shows balance/APY/stats, but the bottom action row is a single full-width "Link a bank account" button.
- Tap → Plaid Link sheet presents on top of the still-open modal.
- User completes Plaid → `public_token` + `account_id` POSTed to `/v1/funding/link-bank` → backend does exchange → processor token → Alpaca ACH relationship.
- Sheet dismisses → the modal is still expanded; action row re-renders with the existing Deposit / Withdraw buttons (their actions stay empty for now — deposit/withdraw UX is a separate thread).

---

## What's already in the iOS app (reusable)

### Network layer

| Piece | File | Notes |
|---|---|---|
| `APIClient` + `APIClientProtocol` | `Sevino/Services/APIClient.swift:3-111` | Generic `get/post/put/patch/delete<T>()`. JWT auto-attached via `tokenProvider` closure (default reads `AuthService.shared.accessToken`). `X-API-Key` attached when `AppConfig.apiKey` non-empty. Snake↔camel conversion built into the encoder/decoder. On non-2xx, decodes response to `APIError` and throws. Singleton `APIClient.shared`. |
| `AuthService` | `Sevino/Services/AuthService.swift` | Owns the Supabase session / access token. |

### Error model

| Piece | File | Notes |
|---|---|---|
| `APIError` | `Sevino/Models/APIError.swift:10-73` | Matches backend `{error, code, detail}` shape exactly. `detail: [String: AnyCodable]?` for dynamic payloads (e.g. the `account_status` field we put inside `ACCOUNT_NOT_ACTIVE`). Namespaced `APIError.Code` has the known codes; `isAuthError`, `isNotFound`, etc. helpers. `LocalizedError` conformance so `error.localizedDescription` returns the backend message. |
| `AnyCodable` | `Sevino/Utils/AnyCodable.swift` | Decodes arbitrary JSON values. Already used by `APIError.detail`. |
| Known codes list | `APIError.swift:30-48` | `CONFLICT`, `VALIDATION_ERROR`, `ALPACA_ERROR`, etc. We'll add `ACCOUNT_NOT_ACTIVE` / `BANK_ALREADY_LINKED` strings inline in the view model — no need to add to this enum unless we want to share them. |

### Existing backend service as a template

| Piece | File | Notes |
|---|---|---|
| `OnboardingServiceProtocol` + `OnboardingService` | `Sevino/Services/OnboardingService.swift:4-31` | **Use this as the template for `FundingService`** — protocol with default impl, singleton `.shared`, uses `APIClient.shared`, one `async throws` method per endpoint. |
| Onboarding DTOs | `Sevino/Models/Onboarding/OnboardingModels.swift` | **Use as template for `FundingDTOs`** — `Encodable` request, `Decodable` response, snake_case auto-handled. |
| Onboarding container state pattern | `Sevino/Views/Onboarding/OnboardingContainerView.swift:352-361` | `saveAndAdvance()` fires an async backend call and advances UI regardless — useful shape for the Plaid success callback. |

### Home screen + the `$` button

| Piece | File | Notes |
|---|---|---|
| Root auth → home routing | `Sevino/ContentView.swift:81` | Auth → Phone → Onboarding → AlpacaSetup → `HomeView`. HomeView is the only authenticated surface. No Settings yet; our entry point is the `$` button only. |
| `HomeView` | `Sevino/Views/Home/HomeView.swift` | Uses a morphing pill-to-modal pattern. 4 expandable pills (Portfolio, Funding, Holdings, Radar). Navigation is `@State` booleans with spring animations (not NavigationStack or `.sheet`). |
| `FundingMorphingView` (the `$` modal) | `Sevino/Views/Home/FundingMorphingView.swift:1-219` | **Central UI change point.** When `isExpanded == false`, renders a `dollarsign` pill. When `true`, renders header + APY badge + stat cards + details table + **`actionButtons`** + infoRow + disclaimer. |
| `actionButtons` (empty!) | `FundingMorphingView.swift:132-148` | Two buttons side-by-side: "Deposit" (line 134) and "Withdraw" (line 141). **Both have `action: {}` — visually present, zero behavior.** These stay untouched in this PR. |
| `HomeViewModel` | `Sevino/ViewModels/Home/HomeViewModel.swift` | `@Observable` (iOS 17+). Holds the greeting, mock portfolio data, and **mock funding data** (`cashBalance`, `cashApy`, `cashThisMonth`, etc. — lines 12-22). **No linked-bank state today.** We compose a `FundingViewModel` onto this. |

### UI mechanics worth knowing

- **`HomeView` uses `@State showFunding: Bool` + spring animations, not a NavigationStack.** Tapping the `$` pill flips `showFunding = true`; the pill morphs in place into the expanded modal. Tapping outside flips it back to `false`.
- **SwiftUI `.sheet` is layered, not replacing.** If we attach `.sheet(isPresented:)` to the modal's `expandedContent`, the Plaid Link UI comes up *on top of* the modal — the modal stays expanded underneath for the entire Plaid session. When the sheet dismisses, the user is still inside the expanded modal.
- **This is why the "no re-tap of `$` needed after Plaid" UX works for free.** `onPlaidSuccess` awaits `loadRelationships()` *before* flipping `isShowingPlaidLink = false`, so by the time the sheet animates away, `hasLinkedBank == true` and SwiftUI's re-render naturally swaps the action row from "Link a bank account" → Deposit/Withdraw. No additional state juggling or modal re-presentation is required.
- Practical implication for implementation: do **not** put the Plaid sheet on `HomeView` or anywhere outside the modal — it must be inside `FundingMorphingView`'s `expandedContent` scope for this layering to work.

### Placeholder files (to be deleted)

| File | Contents |
|---|---|
| `Sevino/Views/Funding/FundingPlaceholder.swift` | `// TODO: Deposit, withdrawal, and bank linking screens` |
| `Sevino/ViewModels/Funding/FundingViewModelPlaceholder.swift` | `// TODO: View models for deposit, withdrawal, and bank linking logic` |
| `Sevino/Models/Funding/FundingModelPlaceholder.swift` | (same TODO shape) |

The three `Funding/` directories already exist — our new files drop in without creating new folders.

### Plaid LinkKit SDK — the caveat

| Fact | Evidence |
|---|---|
| Package declared in project | `Sevino.xcodeproj/project.pbxproj:212` — `C4E361A42F7779AE0091BEA9 /* XCRemoteSwiftPackageReference "plaid-link-ios" */` |
| Version resolved | `Sevino.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved:5-11` — v6.4.7, revision `9022e49010ca6eb2f625bb65990a7ba25f2429d5` |
| **NOT linked to the Sevino app target** | `project.pbxproj:58-65` — the Sevino target's `PBXFrameworksBuildPhase` only lists `Supabase in Frameworks`. No LinkKit. |
| No `XCSwiftPackageProductDependency` entry for LinkKit | `project.pbxproj:761-767` — only Supabase is in this section. |
| No Swift file imports `LinkKit` today | Confirmed via grep across `Sevino/Sevino/` |

**Implication:** `import LinkKit` fails to compile today. Before any Plaid code builds, LinkKit needs to be added as a product dependency of the Sevino target. Two ways:
1. **Xcode UI** (safest): open `Sevino.xcodeproj` → select the `Sevino` target → *General* → *Frameworks, Libraries, and Embedded Content* → `+` → pick `LinkKit` under the `plaid-link-ios` package.
2. **Edit `project.pbxproj`**: add one entry in each of:
   - `PBXBuildFile` (mirroring line 10 for Supabase)
   - `PBXFrameworksBuildPhase` under Sevino target (line 62 list)
   - Sevino target's `packageProductDependencies` (line 126)
   - `XCSwiftPackageProductDependency` section (line 762 shape)
   (Use fresh 24-char hex UUIDs, reference `C4E361A42F7779AE0091BEA9` as the package.)

The implementation plan should do this as the very first commit — otherwise none of the subsequent Swift compiles.

---

## Architectural conventions to follow

From `Sevino/CLAUDE.md` and the existing code:

- **Swift concurrency**: `SWIFT_APPROACHABLE_CONCURRENCY` + `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. All types run on `@MainActor` by default; opt out explicitly with `nonisolated` for background work. View models don't need an explicit `@MainActor` annotation (inherited).
- **MVVM with `@Observable`** (iOS 17+). State lives in view models; views are thin and declarative.
- **Protocol-based DI for testability** — define a `...Protocol`, conform the real service + a mock in tests. Matches `OnboardingServiceProtocol` / `APIClientProtocol`.
- **Singletons via `.shared`** on services (`APIClient.shared`, `AuthService.shared`, `OnboardingService.shared`).
- **snake_case ↔ camelCase** is automatic through `APIClient`'s JSONEncoder/Decoder — DTOs use camelCase Swift, backend uses snake_case JSON, no manual `CodingKeys` unless fields need renaming beyond case.
- **Errors** — services throw `APIError`; view models catch and set `error: APIError?`; views bind to that.

### File placement

| Kind | Path |
|---|---|
| Views | `Sevino/Views/<Feature>/*.swift` |
| View models | `Sevino/ViewModels/<Feature>/*.swift` |
| Services | `Sevino/Services/*.swift` |
| Models | `Sevino/Models/<Feature>/*.swift` |
| Utils (shared helpers) | `Sevino/Utils/*.swift` |
| Unit tests | `SevinoTests/*.swift` |
| UI tests | `SevinoUITests/*.swift` |

---

## Backend endpoints this feature consumes

Only three — all on the already-mounted `/v1/funding/*` router (backend branch `tharsihanariyanayagam/plaid-ach-funding`, commits `d4b8156` / `721ba21` / `b54faca`).

| Method | Path | Body | Response | iOS use |
|---|---|---|---|---|
| `POST` | `/v1/funding/link-token` | — | `{ link_token: string }` | Mint a Plaid Link token before presenting the sheet. |
| `POST` | `/v1/funding/link-bank` | `public_token`, `account_id`, optional `institution_name`, `account_mask`, `account_name`, `nickname` | `AchRelationship` (id, alpaca_relationship_id, institution_name, account_mask, account_type, nickname, status) | Complete the link after Plaid onSuccess. |
| `GET` | `/v1/funding/ach-relationships` | — | `[AchRelationship]` (active only; canceled filtered out server-side) | Drive `hasLinkedBank` state on modal expand. |

All authenticated (JWT). Errors arrive as `APIError` with codes we care about:
- `ACCOUNT_NOT_ACTIVE` — 409, with `detail.account_status`
- `BANK_ALREADY_LINKED` — 409
- `VALIDATION_ERROR` — 422 (unexpected here; Plaid provides the public_token so shape should be valid)
- Auth errors covered by `APIError.isAuthError`

Endpoints we explicitly do **not** call from iOS in this PR:
- `POST /v1/funding/transfers` — deposit/withdraw UX is a separate thread
- `GET /v1/funding/transfers` — history view is deferred
- `DELETE /v1/funding/ach-relationships/{id}` — unlink flow is deferred (if ever — may live in a future Settings screen)

---

## Error-handling surface

`FundingMorphingView` currently has no error UI. Options for where to put error state:

- Inline banner at the top of `expandedContent` — small conditional `Text` in `Color.sevinoNegative` bound to `viewModel.funding.error?.message`.
- SwiftUI `.alert(item:)` on the modal — more jarring, common pattern.

No existing toast/banner component in the codebase (verified via grep for `Banner`, `Toast`, `Notice`). Simplest: inline banner. Surface on:

| Code | Copy |
|---|---|
| `ACCOUNT_NOT_ACTIVE` | "Your brokerage account is still being reviewed." |
| `BANK_ALREADY_LINKED` | "This bank is already linked." (+ auto-refresh relationships) |
| Plaid `onExit(error:)` non-nil | "Couldn't connect to your bank. Try again." |
| Plaid user-cancel (nil error) | Silent |
| Other | `error.localizedDescription` (falls through to `"Something went wrong"`) |

---

## Testing baseline

- pytest-style XCTest at `SevinoTests/`. No existing funding tests.
- Protocol-based DI means mocking is straightforward: conform `FundingServiceProtocol` with a test double that returns canned `AchRelationshipDTO`s or throws `APIError`s.
- End-to-end with real Plaid + Alpaca sandbox is done via the backend's `scripts/seed_funding_sandbox.py` + `scripts/funding_smoke.sh` — iOS manual verification piggy-backs on the same seeded user (`funding-smoke@sevino.test`).

---

## Open blockers discovered during research

1. **LinkKit not linked to the Sevino target** — see the "Plaid LinkKit SDK — the caveat" section above. Must be resolved before any Plaid Swift code compiles.
2. **No banner/toast component exists** — we'll inline a simple `Text` banner unless we decide to build a reusable one.
3. **The morphing modal does not currently await anything** — refreshing `relationships` on expand requires choosing a lifecycle hook (`.task(id: isExpanded)`, `.onChange(of:)`, or a dedicated method on the view model called from `HomeView` when `showFunding` flips). Decision deferred to the implementation plan.

---

## Reference — commits that produced the backend these endpoints live on

Branch: `tharsihanariyanayagam/plaid-ach-funding`

| Phase | Commit | What |
|---|---|---|
| 1 | `5f6d4f4` | Fernet encryption helper |
| 2 | `d4b8156` | PlaidService (link-token, exchange, processor-token) |
| 3 | `6d8b8cc` | Alpaca broker ACH + transfer methods |
| 4 | `e0e4051` | Plaid item + ACH relationship repositories |
| 5 | `698dad3` | FundingService orchestration |
| 6 | `721ba21` | `/v1/funding` schemas + router |
| 7 | `b54faca` | Router mounted + PlaidService in lifespan |
| 8 | `74f5dfa` | Sandbox smoke scripts |

Backend smokes pass end-to-end (verified in chat). Frontend now builds on top.
