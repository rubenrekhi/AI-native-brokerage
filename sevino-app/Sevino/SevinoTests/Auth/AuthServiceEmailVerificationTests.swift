import XCTest
import Supabase
@testable import Sevino

/// Integration tests for the email verification surface on AuthService.
/// Hits real local Supabase (make infra must be running). Skipped unless
/// INTEGRATION_TESTS=1 and the SUPABASE_TEST_* env vars are set.
@MainActor
final class AuthServiceEmailVerificationTests: XCTestCase {

    private var client: SupabaseClient!
    private var serviceRoleClient: SupabaseClient!
    private var authService: AuthService!
    private var createdUserID: UUID?
    private let testEmail = "email-verify-\(UUID().uuidString.prefix(8))@test.com"
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

    private static func unreachableReason(for baseURL: URL) async -> String? {
        let healthURL = baseURL.appendingPathComponent("auth/v1/health")
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2.0
        config.timeoutIntervalForResource = 2.0
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }

        do {
            let (_, response) = try await session.data(from: healthURL)
            guard let http = response as? HTTPURLResponse else { return "non-HTTP response" }
            guard (200..<300).contains(http.statusCode) else { return "HTTP \(http.statusCode)" }
            return nil
        } catch {
            return "\(error.localizedDescription)"
        }
    }

    override func tearDown() async throws {
        guard let client, let serviceRoleClient else { return }

        try? await client.auth.signOut()

        if let userID = createdUserID {
            try? await serviceRoleClient.auth.admin.deleteUser(id: userID)
            createdUserID = nil
        }
    }

    /// Creates an unconfirmed user via signUp and captures the ID via admin
    /// API for tearDown cleanup. No session is established — under
    /// `enable_confirmations = true`, signUp doesn't return one.
    private func signUpUnconfirmed() async throws {
        try await authService.signUp(email: testEmail, password: testPassword)
        // GoTrue lowercases emails on storage, so compare case-insensitively
        // against `testEmail` (which has an uppercase UUID-prefix segment).
        let target = testEmail.lowercased()
        let response = try await serviceRoleClient.auth.admin.listUsers()
        createdUserID = response.users.first(where: { ($0.email ?? "").lowercased() == target })?.id
        try await Task.sleep(for: .milliseconds(100))
    }

    /// Confirms the email via admin API and signs in to establish a session.
    /// For tests that need to assert verified-and-signed-in state.
    private func signUpAndAuthenticate() async throws {
        try await signUpUnconfirmed()
        guard let userID = createdUserID else {
            return XCTFail("admin lookup did not return a user ID for \(testEmail)")
        }
        _ = try await serviceRoleClient.auth.admin.updateUserById(
            userID,
            attributes: AdminUserAttributes(emailConfirm: true)
        )
        try await authService.signIn(email: testEmail, password: testPassword)
        try await Task.sleep(for: .milliseconds(100))
    }

    // MARK: - Initial state

    /// After signUp + admin email-confirm + signIn, the listener mirrors the
    /// session's confirmed state on `isEmailVerified`.
    func testIsEmailVerifiedMirrorsSessionState() async throws {
        try await signUpAndAuthenticate()
        let session = try await client.auth.session
        XCTAssertNotNil(session.user.emailConfirmedAt, "post-confirm session must report emailConfirmedAt")
        XCTAssertEqual(authService.isEmailVerified, session.user.emailConfirmedAt != nil)
        XCTAssertTrue(authService.isEmailVerified)
    }

    func testCanResendByDefault() async throws {
        try await signUpUnconfirmed()
        XCTAssertTrue(authService.canResendEmailConfirmation)
        XCTAssertNil(authService.emailResendAvailableAt)
    }

    // MARK: - Resend
    //
    // GoTrue has a hardcoded ~60s per-user/per-IP cooldown on the
    // /auth/v1/resend endpoint that fires regardless of the CLI's
    // `max_frequency` and `email_sent` settings (those only apply when SMTP
    // is configured; local dev uses Inbucket). Integration-testing the
    // resend wrapper would require either a 60s pre-test wait or a custom
    // patched GoTrue. The resend logic itself — `canResendEmailConfirmation`,
    // `emailResendAvailableAt`, `EmailVerificationError.resendCooldown` — is
    // fully covered at the unit-test layer in
    // `EmailVerificationViewModelTests` (see the cooldown / verifiedBlocksResend /
    // resendAfterCooldownRestartsCountdown / resendCooldownErrorMaps tests).
    // The handful of contract assertions left here would just re-test
    // Supabase, not our code.

    func testResendDoesNotThrowAfterSignup() async throws {
        throw XCTSkip("GoTrue has a hardcoded ~60s resend cooldown — covered by unit tests instead")
    }

    func testResendSetsCooldown() async throws {
        throw XCTSkip("GoTrue has a hardcoded ~60s resend cooldown — covered by unit tests instead")
    }

    func testResendWithinCooldownThrows() async throws {
        throw XCTSkip("GoTrue has a hardcoded ~60s resend cooldown — covered by unit tests instead")
    }

    // MARK: - Sign out

    func testSignOutResetsEmailVerified() async throws {
        try await signUpAndAuthenticate()
        XCTAssertTrue(authService.isEmailVerified)
        XCTAssertTrue(authService.isAuthenticated)

        try await authService.signOut()
        try await Task.sleep(for: .milliseconds(100))

        XCTAssertFalse(authService.isEmailVerified)
        XCTAssertFalse(authService.isAuthenticated)
    }
}
