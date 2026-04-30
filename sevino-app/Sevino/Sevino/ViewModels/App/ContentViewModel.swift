import Foundation

/// Drives the root view routing between email verification, phone capture,
/// onboarding, Alpaca setup, and home. Owns the onboarding status check and
/// related resume data so the view stays declarative.
@Observable
final class ContentViewModel {
    private let onboardingService: any OnboardingServiceProtocol
    private let phoneVerificationService: any PhoneVerificationServiceProtocol
    /// Exposed so `ContentView` can thread the same auth service into screens
    /// that own their own VM (e.g. `EmailVerificationView`). Without this, those
    /// screens' default-arg `AuthService.shared` would diverge from the one
    /// `ContentViewModel` consults for routing decisions — fatal for tests
    /// that inject a fake. `@ObservationIgnored` since the reference is a
    /// constant dependency; the macro shouldn't track it as observable state.
    @ObservationIgnored
    let authService: any AuthServiceProtocol

    // MARK: - Routing

    private(set) var route: AuthenticatedRoute = .idle

    // MARK: - Transient UI state

    private(set) var isLoading = false
    private(set) var showPhoneError = false
    private(set) var error: String?

    init(
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        phoneVerificationService: any PhoneVerificationServiceProtocol = PhoneVerificationService.shared,
        authService: any AuthServiceProtocol = AuthService.shared
    ) {
        self.onboardingService = onboardingService
        self.phoneVerificationService = phoneVerificationService
        self.authService = authService
    }

    // MARK: - Auth transitions

    /// Fresh signup: skip the status check and go straight to email verification.
    /// Supabase auto-sent the confirmation OTP as a side effect of `signUp`, so
    /// the user lands on the OTP screen with a code already in flight. The email
    /// is read from the active session — `AuthView` doesn't pass it through.
    ///
    /// If a future auth provider (OAuth, magic link, etc.) lands on this method
    /// with an already-confirmed session, skip the gate — `EmailVerificationView`
    /// only advances on a `false → true` transition of `isEmailVerified`, so an
    /// already-verified user would otherwise stall on the OTP screen with no
    /// trigger to advance.
    func startFreshSignUpFlow() async {
        if authService.isEmailVerified {
            route = .phone
            return
        }
        guard let email = await authService.currentEmail else {
            // Defensive — `signUp` succeeded so a session must exist, but bail
            // safely to the retry view rather than crashing on a force unwrap.
            route = .statusCheckFailed
            return
        }
        route = .emailVerification(email: email)
    }

    func completeOnboarding(userName: String) {
        route = .alpacaSetup(step: 1, userName: userName, data: nil)
    }

    func completeAlpacaSetup() {
        route = .home
    }

    // MARK: - Async operations

    /// Dispatches the OTP and advances to the verification screen. The phone
    /// number itself is *not* persisted yet — it stays in iOS memory (passed
    /// through the `.phoneVerification` route) until `/v1/auth/phone/confirm`
    /// writes it atomically with `phone_verified_at` and the welcome step.
    /// This way `user_profiles.phone_number` only ever holds verified phones,
    /// and resume routing can never see `onboarding_step="welcome"` on an
    /// unverified user (SEV-448). A duplicate-phone rejection
    /// (`PHONE_NUMBER_TAKEN`) keeps the user on `.phone` with a tailored
    /// error rather than stranding them on the OTP screen with no code.
    func savePhoneNumber(_ phoneNumber: String) async {
        error = nil
        showPhoneError = false
        isLoading = true
        defer { isLoading = false }
        do {
            try await phoneVerificationService.sendOTP(phoneNumber: phoneNumber)
            // Normalize through PhoneFormatter so the route's associated value
            // has the same `(555) 123-4567` shape whether we got here from
            // PhoneNumberView (already pretty) or from a future caller that
            // forwards raw digits — and so the OTP screen title is consistent
            // with the resume path's auth.users-sourced format.
            route = .phoneVerification(phoneNumber: PhoneFormatter.format(phoneNumber))
        } catch let caughtError {
            error = phoneSaveErrorMessage(for: caughtError)
            showPhoneError = true
        }
    }

    /// Translates phone-step errors into a user-facing string. The duplicate
    /// case gets the dedicated copy so the user understands why advancing was
    /// blocked; everything else falls back to the backend's localized message.
    private func phoneSaveErrorMessage(for error: Error) -> String {
        if let apiError = error as? APIError, apiError.code == "PHONE_NUMBER_TAKEN" {
            return L10n.Auth.phoneNumberTaken
        }
        return error.localizedDescription
    }

    /// Called by `PhoneVerificationView` once the OTP confirm succeeds. Advances
    /// the user into the 18-step onboarding flow.
    func onPhoneVerified() {
        route = .onboarding(step: 1, data: nil)
    }

    /// Called when the user taps the back chevron on `PhoneVerificationView`.
    /// Returns to phone capture so they can edit the number; the in-flight OTP
    /// becomes irrelevant once a new number is submitted.
    func onChangeNumber() {
        route = .phone
    }

    /// Called by `EmailVerificationView` once Supabase flips
    /// `isEmailVerified = true`. Advances to phone capture, the next gate
    /// before onboarding.
    func onEmailVerified() {
        route = .phone
    }

    /// Fetches onboarding status and routes to the matching destination. On failure,
    /// routes to `.statusCheckFailed` so the view shows a retry prompt instead of
    /// silently falling through to home.
    ///
    /// Email verification is checked locally first — Supabase tracks
    /// `isEmailVerified` on the session, so an unverified user is routed to
    /// `.emailVerification` without bothering the backend (no server-side
    /// state would be resumeable anyway).
    func checkOnboardingStatus() async {
        error = nil
        route = .loading

        if !authService.isEmailVerified {
            let email = await authService.currentEmail
            // Re-read `isEmailVerified` after the await — the Supabase
            // `userUpdated` listener can land between the sync read above and
            // resumption here, in which case fall through to the status check.
            if authService.isEmailVerified {
                // race: verification landed mid-await; proceed normally
            } else if let email {
                route = .emailVerification(email: email)
                return
            } else {
                // `error` intentionally stays nil — `StatusCheckRetryView`
                // shows generic copy and ignores the field, so leaving it
                // unset matches the no-network baseline.
                route = .statusCheckFailed
                return
            }
        }

        do {
            let status = try await onboardingService.getStatus()
            apply(OnboardingResumeManager.destination(from: status))
        } catch let caughtError {
            error = caughtError.localizedDescription
            route = .statusCheckFailed
        }
    }

    func clearError() {
        error = nil
        showPhoneError = false
    }

    private func apply(_ destination: OnboardingResumeManager.Destination) {
        switch destination {
        case .home:
            route = .home
        case .phone:
            route = .phone
        case .phoneVerification(let phoneNumber):
            route = .phoneVerification(phoneNumber: phoneNumber)
        case .onboarding(let step, let data):
            route = .onboarding(step: step, data: data)
        case .alpacaSetup(let step, let data):
            route = .alpacaSetup(step: step, userName: data.userName, data: data)
        case .loading:
            break
        }
    }
}
