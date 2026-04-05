import Foundation

/**
 Observable auth state for SwiftUI views.

 The root view observes `isAuthenticated` to decide whether to show the
 auth flow or the main app. Delegates all auth logic to AuthService.

 `isAuthenticated` is a computed property that reads directly from the
 service. SwiftUI's observation tracking follows the access chain, so
 when `AuthService.isAuthenticated` changes (via Supabase auth events),
 any view reading this property re-renders automatically.
 */
@Observable
final class AuthViewModel {
    private let authService: AuthServiceProtocol

    var isAuthenticated: Bool { authService.isAuthenticated }
    private(set) var isLoading = false
    private(set) var requiresEmailConfirmation = false
    var authError: String?

    init(authService: AuthServiceProtocol = AuthService.shared) {
        self.authService = authService
    }

    func signUp(email: String, password: String) async {
        authError = nil
        isLoading = true
        defer { isLoading = false }

        do {
            try await authService.signUp(email: email, password: password)
            requiresEmailConfirmation = true
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

        do {
            try await authService.signOut()
            requiresEmailConfirmation = false
        } catch {
            authError = error.localizedDescription
        }
    }
}
