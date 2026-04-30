import Auth
import Foundation
import Supabase

protocol AuthServiceProtocol {
    var isAuthenticated: Bool { get }
    var isEmailVerified: Bool { get }
    var emailResendAvailableAt: Date? { get }
    var canResendEmailConfirmation: Bool { get }
    var accessToken: String? { get async }
    var currentEmail: String? { get async }
    func signUp(email: String, password: String) async throws
    func signIn(email: String, password: String) async throws
    func signOut() async throws
    func updatePassword(currentPassword: String, newPassword: String) async throws
    func resendEmailConfirmation(email: String) async throws
    func verifyEmailConfirmation(email: String, code: String) async throws
}

enum PasswordChangeError: LocalizedError {
    case sessionMissingEmail
    case incorrectCurrentPassword
    case updateFailed

    var errorDescription: String? {
        switch self {
        case .sessionMissingEmail, .updateFailed:
            L10n.Settings.changePasswordGenericError
        case .incorrectCurrentPassword:
            L10n.Settings.currentPasswordIncorrectError
        }
    }
}

enum EmailVerificationError: Error {
    case resendCooldown
}

/**
 Wraps Supabase auth and tracks authentication state.

 Listens to auth events (sign in, sign out, token refresh) via an
 async stream and keeps `isAuthenticated` up to date. Views observe
 this through `AuthViewModel`, never directly.
 */
@Observable
final class AuthService: AuthServiceProtocol {
    static let shared = AuthService()

    private(set) var isAuthenticated = false
    private(set) var isEmailVerified = false
    private(set) var emailResendAvailableAt: Date?
    private let client: SupabaseClient
    private let resendCooldown: TimeInterval = 15
    private var listenerTask: Task<Void, Never>?

    var canResendEmailConfirmation: Bool {
        guard let availableAt = emailResendAvailableAt else { return true }
        return Date() >= availableAt
    }

    private init() {
        self.client = supabase
        startListening()
    }

    // For integration tests — allows injecting a test SupabaseClient
    init(client: SupabaseClient) {
        self.client = client
        startListening()
    }

    deinit {
        listenerTask?.cancel()
    }

    // Return values discarded — signUp returns AuthResponse and signIn returns
    // Session, but auth state is tracked via the authStateChanges listener instead.
    func signUp(email: String, password: String) async throws {
        _ = try await client.auth.signUp(email: email, password: password)
    }

    func signIn(email: String, password: String) async throws {
        _ = try await client.auth.signIn(email: email, password: password)
    }

    func signOut() async throws {
        try await client.auth.signOut()
    }

    // Reauthenticates by signing in with the current password before applying
    // the change — Supabase's `update(user:)` only checks the session JWT, so
    // without this step anyone on an unlocked device could rotate the password.
    func updatePassword(currentPassword: String, newPassword: String) async throws {
        let session = try await client.auth.session
        guard let email = session.user.email else {
            throw PasswordChangeError.sessionMissingEmail
        }
        do {
            _ = try await client.auth.signIn(email: email, password: currentPassword)
        } catch {
            throw PasswordChangeError.incorrectCurrentPassword
        }
        do {
            _ = try await client.auth.update(user: UserAttributes(password: newPassword))
        } catch {
            throw PasswordChangeError.updateFailed
        }
    }

    func resendEmailConfirmation(email: String) async throws {
        guard canResendEmailConfirmation else {
            throw EmailVerificationError.resendCooldown
        }
        try await client.auth.resend(email: email, type: .signup)
        emailResendAvailableAt = Date().addingTimeInterval(resendCooldown)
    }

    func verifyEmailConfirmation(email: String, code: String) async throws {
        _ = try await client.auth.verifyOTP(email: email, token: code, type: .signup)
    }

    // Used by APIClient to attach the JWT to requests
    var accessToken: String? {
        get async { try? await client.auth.session.accessToken }
    }

    /// Email of the active Supabase session, or nil if no session exists or the
    /// session is missing the field (shouldn't happen post-signup but bails safely).
    /// Read from the JWT — there is no listener-driven local mirror for this since
    /// it doesn't change once the account is created.
    var currentEmail: String? {
        get async { try? await client.auth.session.user.email }
    }

    private func startListening() {
        listenerTask = Task { [weak self, client] in
            for await (event, session) in client.auth.authStateChanges {
                guard let self else { return }

                switch event {
                case .initialSession, .signedIn, .tokenRefreshed, .userUpdated:
                    self.isAuthenticated = session != nil
                    self.isEmailVerified = session?.user.emailConfirmedAt != nil
                case .signedOut:
                    self.isAuthenticated = false
                    self.isEmailVerified = false
                default:
                    break
                }
            }
        }
    }
}
