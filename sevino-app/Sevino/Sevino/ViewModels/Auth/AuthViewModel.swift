import Foundation

/**
 Observable auth state for SwiftUI views.

 The root view observes `isAuthenticated` to decide whether to show the
 auth flow or the main app. Delegates all auth logic to AuthService.

 `isAuthenticated` is a computed property that reads directly from the
 service. SwiftUI's observation tracking follows the access chain, so
 when `AuthService.isAuthenticated` changes (via Supabase auth events),
 any view reading this property re-renders automatically.

 ## Pending email confirmation

 With Supabase `enable_confirmations = true`, signUp returns successfully
 but does NOT issue a session — the user has to verify the OTP first.
 In that window the user is unauthenticated yet still has a flow to
 finish. `pendingConfirmationEmail` is set in `signUp` so the root view
 can route the user to `EmailVerificationView` even though
 `isAuthenticated == false`. The flag clears on signOut, on a manual
 `clearPendingConfirmation()` (back-chevron / change-email), and is
 implicitly stale once isAuthenticated flips true (the authenticated
 path then takes over).
 */
@Observable
final class AuthViewModel {
    /// Exposed so the root view can thread the same service into
    /// `EmailVerificationView` when routing the pre-auth confirmation step.
    /// Without this, that screen would default to `AuthService.shared` and
    /// diverge from this VM's listener-driven `isAuthenticated`.
    /// `@ObservationIgnored` since the reference itself never mutates;
    /// keeps the macro from registering it as a tracked dependency.
    @ObservationIgnored
    let authService: AuthServiceProtocol

    var isAuthenticated: Bool { authService.isAuthenticated }
    private(set) var isLoading = false
    private(set) var requiresEmailConfirmation = false
    private(set) var pendingConfirmationEmail: String?
    private(set) var authError: String?

    init(authService: AuthServiceProtocol = AuthService.shared) {
        self.authService = authService
    }

    func clearError() {
        authError = nil
    }

    /// Drop the pending email confirmation state. Called from the email
    /// verification screen's back-chevron in the pre-auth window so the
    /// user can retry signup with a different address.
    func clearPendingConfirmation() {
        requiresEmailConfirmation = false
        pendingConfirmationEmail = nil
    }

    func signUp(email: String, password: String) async {
        authError = nil
        // Clear any stale stash up-front so a failed retry can't leave the
        // user pointed at a previous email's verification flow.
        pendingConfirmationEmail = nil
        requiresEmailConfirmation = false
        isLoading = true
        defer { isLoading = false }

        do {
            try await authService.signUp(email: email, password: password)
            requiresEmailConfirmation = true
            pendingConfirmationEmail = email
        } catch {
            authError = error.localizedDescription
        }
    }

    func signIn(email: String, password: String) async {
        authError = nil
        isLoading = true
        defer { isLoading = false }

        do {
            try await authService.signIn(email: email, password: password)
        } catch {
            authError = error.localizedDescription
        }
    }

    func signOut() async {
        authError = nil
        isLoading = true
        defer { isLoading = false }

        do {
            try await authService.signOut()
            requiresEmailConfirmation = false
            pendingConfirmationEmail = nil
        } catch {
            authError = error.localizedDescription
        }
    }
}
