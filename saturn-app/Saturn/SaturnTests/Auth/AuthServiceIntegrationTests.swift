import XCTest
import Supabase
@testable import Saturn

/// Integration tests that hit real local Supabase (make infra must be running).
/// These are skipped in CI — only run locally during development.
final class AuthServiceIntegrationTests: XCTestCase {

    private var client: SupabaseClient!
    private var authService: AuthService!
    private let testEmail = "integration-test-\(UUID().uuidString.prefix(8))@test.com"
    private let testPassword = "testpassword123"

    override func setUp() async throws {
        client = SupabaseClient(
            supabaseURL: URL(string: "http://127.0.0.1:54321")!,
            supabaseKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
        )
        authService = AuthService(client: client)

        // Give the auth state listener time to start
        try await Task.sleep(for: .milliseconds(100))
    }

    override func tearDown() async throws {
        // Clean up — sign out if still signed in
        try? await client.auth.signOut()
    }

    func testSignUpAndSignIn() async throws {
        // Sign up creates a new account (auto-confirmed in local Supabase)
        try await authService.signUp(email: testEmail, password: testPassword)

        // Sign out first so we can test sign in
        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertFalse(authService.isAuthenticated)

        // Sign in with the account we just created
        try await authService.signIn(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertTrue(authService.isAuthenticated)
    }

    func testSignOut() async throws {
        try await authService.signUp(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertTrue(authService.isAuthenticated)

        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertFalse(authService.isAuthenticated)
    }

    func testSignInWithWrongPasswordThrows() async {
        // Create account first
        try? await authService.signUp(email: testEmail, password: testPassword)
        try? await authService.signOut()

        do {
            try await authService.signIn(email: testEmail, password: "wrongpassword")
            XCTFail("Expected sign in to throw")
        } catch {
            XCTAssertFalse(authService.isAuthenticated)
        }
    }
}
