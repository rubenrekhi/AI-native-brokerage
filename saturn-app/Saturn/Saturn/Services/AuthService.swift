import Auth
import Foundation
import Supabase

// Protocol for dependency injection — use MockAuthService in tests
protocol AuthServiceProtocol {
    var isAuthenticated: Bool { get }
    func signUp(email: String, password: String) async throws
    func signIn(email: String, password: String) async throws
    func signOut() async throws
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
    private let client: SupabaseClient
    private var listenerTask: Task<Void, Never>?

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

    private func startListening() {
        listenerTask = Task { [weak self, client] in
            for await (event, session) in client.auth.authStateChanges {
                guard let self else { return }

                switch event {
                case .initialSession, .signedIn, .tokenRefreshed:
                    self.isAuthenticated = session != nil
                case .signedOut:
                    self.isAuthenticated = false
                default:
                    break
                }
            }
        }
    }
}
