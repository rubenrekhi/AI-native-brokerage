import XCTest
import Supabase
@testable import Sevino

/// Integration tests that hit real local Supabase (make infra must be running).
/// Skipped unless INTEGRATION_TESTS=1 is set, the SUPABASE_TEST_* env vars are
/// populated, and the Supabase URL is reachable.
@MainActor
final class AuthServiceIntegrationTests: XCTestCase {

    private var client: SupabaseClient!
    private var serviceRoleClient: SupabaseClient!
    private var authService: AuthService!
    private var createdUserID: UUID?
    private let testEmail = "integration-test-\(UUID().uuidString.prefix(8))@test.com"
    private let testPassword = "testpassword123"

    override func setUp() async throws {
        let env = ProcessInfo.processInfo.environment

        try XCTSkipUnless(
            env["INTEGRATION_TESTS"] == "1",
            "Set INTEGRATION_TESTS=1 to run"
        )

        let urlString = env["SUPABASE_TEST_URL"]
        let anonKey = env["SUPABASE_TEST_ANON_KEY"]
        let serviceKey = env["SUPABASE_TEST_SERVICE_ROLE_KEY"]

        try XCTSkipUnless(
            urlString != nil && anonKey != nil && serviceKey != nil,
            "SUPABASE_TEST_URL / SUPABASE_TEST_ANON_KEY / SUPABASE_TEST_SERVICE_ROLE_KEY must be set"
        )

        let supabaseURL = try XCTUnwrap(URL(string: urlString!), "SUPABASE_TEST_URL is not a valid URL: \(urlString!)")

        if let reason = await Self.unreachableReason(for: supabaseURL) {
            throw XCTSkip("Local Supabase not reachable at \(supabaseURL): \(reason). Run `make infra` in sevino-api/ to start it.")
        }

        client = SupabaseClient(supabaseURL: supabaseURL, supabaseKey: anonKey!)
        serviceRoleClient = SupabaseClient(supabaseURL: supabaseURL, supabaseKey: serviceKey!)
        authService = await MainActor.run { AuthService(client: client) }

        try await Task.sleep(for: .milliseconds(100))
    }

    /// Probes `<baseURL>/auth/v1/health`. Returns `nil` on 2xx (reachable) or a
    /// human-readable reason string otherwise. Uses a short-timeout URLSession
    /// so CI doesn't stall when Supabase isn't running.
    private static func unreachableReason(for baseURL: URL) async -> String? {
        let healthURL = baseURL.appendingPathComponent("auth/v1/health")
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2.0
        config.timeoutIntervalForResource = 2.0
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }

        do {
            let (_, response) = try await session.data(from: healthURL)
            guard let http = response as? HTTPURLResponse else {
                return "non-HTTP response"
            }
            guard (200..<300).contains(http.statusCode) else {
                return "HTTP \(http.statusCode)"
            }
            return nil
        } catch {
            return "\(error.localizedDescription)"
        }
    }

    override func tearDown() async throws {
        guard let client, let serviceRoleClient else { return }

        try? await client.auth.signOut()

        // Delete the test user by ID via service role (admin API)
        if let userID = createdUserID {
            try? await serviceRoleClient.auth.admin.deleteUser(id: userID)
            createdUserID = nil
        }
    }

    func testSignUpAndSignIn() async throws {
        // signUp leaves the user unconfirmed (no session) under
        // `enable_confirmations = true`. Admin-confirm so the subsequent
        // signIn isn't blocked by "Email not confirmed".
        try await signUpAndConfirm()

        try await authService.signIn(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertTrue(authService.isAuthenticated)
    }

    func testSignOut() async throws {
        try await signUpAndAuthenticate()
        XCTAssertTrue(authService.isAuthenticated)

        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertFalse(authService.isAuthenticated)
    }

    func testSignInWithWrongPasswordThrows() async throws {
        // Email must be confirmed first; otherwise signIn fails on the
        // email-not-confirmed check before ever reaching the password check.
        try await signUpAndConfirm()

        do {
            try await authService.signIn(email: testEmail, password: "wrongpassword")
            XCTFail("Expected sign in to throw")
        } catch {
            XCTAssertFalse(authService.isAuthenticated)
        }
    }

    // MARK: - Helpers

    /// Creates an unconfirmed user via signUp and looks up the ID via the
    /// admin API so tearDown can delete it. Does NOT establish a session —
    /// `enable_confirmations = true` requires explicit confirmation first.
    private func signUpUnconfirmed() async throws {
        try await authService.signUp(email: testEmail, password: testPassword)
        createdUserID = try await fetchUserID(email: testEmail)
    }

    /// Like `signUpUnconfirmed` but additionally flips the user's email to
    /// confirmed via the admin API, so subsequent signIn succeeds. Does not
    /// sign in — the caller decides when.
    private func signUpAndConfirm() async throws {
        try await signUpUnconfirmed()
        guard let userID = createdUserID else {
            return XCTFail("admin lookup did not return a user ID for \(testEmail)")
        }
        _ = try await serviceRoleClient.auth.admin.updateUserById(
            userID,
            attributes: AdminUserAttributes(emailConfirm: true)
        )
    }

    /// One-shot path for tests that just need a verified, signed-in user:
    /// signUp → admin-confirm → signIn.
    private func signUpAndAuthenticate() async throws {
        try await signUpAndConfirm()
        try await authService.signIn(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
    }

    private func fetchUserID(email: String) async throws -> UUID? {
        // GoTrue lowercases emails on storage, so compare case-insensitively
        // against the test email (which has an uppercase UUID-prefix segment).
        let target = email.lowercased()
        let response = try await serviceRoleClient.auth.admin.listUsers()
        return response.users.first(where: { ($0.email ?? "").lowercased() == target })?.id
    }
}
