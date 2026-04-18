import XCTest
import Supabase
@testable import Sevino

/// Integration tests that hit real local Supabase (make infra must be running).
/// Skipped by default — set INTEGRATION_TESTS=1 plus the Supabase env vars to run.
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

        let url = try XCTUnwrap(env["SUPABASE_TEST_URL"], "SUPABASE_TEST_URL not set")
        let anonKey = try XCTUnwrap(env["SUPABASE_TEST_ANON_KEY"], "SUPABASE_TEST_ANON_KEY not set")
        let serviceKey = try XCTUnwrap(env["SUPABASE_TEST_SERVICE_ROLE_KEY"], "SUPABASE_TEST_SERVICE_ROLE_KEY not set")

        client = SupabaseClient(
            supabaseURL: URL(string: url)!,
            supabaseKey: anonKey
        )
        serviceRoleClient = SupabaseClient(
            supabaseURL: URL(string: url)!,
            supabaseKey: serviceKey
        )
        authService = await MainActor.run { AuthService(client: client) }

        try await Task.sleep(for: .milliseconds(100))
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
        try await authService.signUp(email: testEmail, password: testPassword)
        createdUserID = try? await client.auth.session.user.id

        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))
        var isAuth = authService.isAuthenticated
        XCTAssertFalse(isAuth)

        try await authService.signIn(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
        isAuth = authService.isAuthenticated
        XCTAssertTrue(isAuth)
    }

    func testSignOut() async throws {
        try await authService.signUp(email: testEmail, password: testPassword)
        createdUserID = try? await client.auth.session.user.id
        try await Task.sleep(for: .milliseconds(100))
        var isAuth = authService.isAuthenticated
        XCTAssertTrue(isAuth)

        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))
        isAuth = authService.isAuthenticated
        XCTAssertFalse(isAuth)
    }

    func testSignInWithWrongPasswordThrows() async {
        try? await authService.signUp(email: testEmail, password: testPassword)
        createdUserID = try? await client.auth.session.user.id
        try? await authService.signOut()

        do {
            try await authService.signIn(email: testEmail, password: "wrongpassword")
            XCTFail("Expected sign in to throw")
        } catch {
            let isAuth = authService.isAuthenticated
            XCTAssertFalse(isAuth)
        }
    }
}
