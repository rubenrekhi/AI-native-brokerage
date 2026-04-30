import XCTest
@testable import Sevino

@MainActor
final class AuthViewModelTests: XCTestCase {

    private var mock: MockAuthService!
    private var viewModel: AuthViewModel!

    override func setUp() {
        mock = MockAuthService()
        viewModel = AuthViewModel(authService: mock)
    }

    // MARK: - Sign In

    func testSignInSuccess() async {
        await viewModel.signIn(email: "test@test.com", password: "password123")

        XCTAssertTrue(viewModel.isAuthenticated)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.authError)
    }

    func testSignInFailureSetsError() async {
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Invalid credentials"])

        await viewModel.signIn(email: "test@test.com", password: "wrong")

        XCTAssertFalse(viewModel.isAuthenticated)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(viewModel.authError, "Invalid credentials")
    }

    func testSignInClearsPreviousError() async {
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Error"])
        await viewModel.signIn(email: "test@test.com", password: "wrong")
        XCTAssertNotNil(viewModel.authError)

        mock.errorToThrow = nil
        await viewModel.signIn(email: "test@test.com", password: "password123")

        XCTAssertNil(viewModel.authError)
    }

    // MARK: - Sign Up

    func testSignUpSuccessSetsConfirmationFlag() async {
        await viewModel.signUp(email: "new@test.com", password: "password123")

        XCTAssertTrue(viewModel.requiresEmailConfirmation)
        XCTAssertFalse(viewModel.isAuthenticated)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.authError)
    }

    func testSignUpSuccessStashesEmailForPostSignupRouting() async {
        // ContentView reads `pendingConfirmationEmail` to render the email
        // verification screen in the pre-auth window — when Supabase has
        // `enable_confirmations = true`, signUp returns no session so
        // `isAuthenticated` stays false but the user still has a flow to finish.
        await viewModel.signUp(email: "new@test.com", password: "password123")

        XCTAssertEqual(viewModel.pendingConfirmationEmail, "new@test.com")
    }

    func testSignUpFailureSetsError() async {
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Email already taken"])

        await viewModel.signUp(email: "existing@test.com", password: "password123")

        XCTAssertFalse(viewModel.requiresEmailConfirmation)
        XCTAssertNil(viewModel.pendingConfirmationEmail, "failed signup must not strand the email in the pre-auth state")
        XCTAssertEqual(viewModel.authError, "Email already taken")
    }

    func testClearPendingConfirmationResetsBothFields() async {
        await viewModel.signUp(email: "new@test.com", password: "password123")
        XCTAssertNotNil(viewModel.pendingConfirmationEmail)

        viewModel.clearPendingConfirmation()

        XCTAssertNil(viewModel.pendingConfirmationEmail)
        XCTAssertFalse(viewModel.requiresEmailConfirmation)
    }

    func testReSignupOverwritesStashedEmail() async {
        await viewModel.signUp(email: "first@test.com", password: "password123")
        XCTAssertEqual(viewModel.pendingConfirmationEmail, "first@test.com")

        await viewModel.signUp(email: "second@test.com", password: "password123")

        XCTAssertEqual(viewModel.pendingConfirmationEmail, "second@test.com",
                       "the second signup must point the verification flow at the new email, not the old one")
    }

    func testFailedSignupClearsStaleStash() async {
        // First signup succeeds and stashes the email.
        await viewModel.signUp(email: "first@test.com", password: "password123")
        XCTAssertEqual(viewModel.pendingConfirmationEmail, "first@test.com")

        // Second signup fails — the stale stash from the first signup must NOT
        // strand the user pointed at "first@test.com"'s verification flow.
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Email already taken"])
        await viewModel.signUp(email: "second@test.com", password: "password123")

        XCTAssertNil(viewModel.pendingConfirmationEmail,
                     "a failed signup must clear the stale stash so the user isn't stranded on a previous email's verification screen")
        XCTAssertFalse(viewModel.requiresEmailConfirmation)
        XCTAssertEqual(viewModel.authError, "Email already taken")
    }

    // MARK: - Sign Out

    func testSignOutSuccess() async {
        mock.isAuthenticated = true
        viewModel = AuthViewModel(authService: mock)

        await viewModel.signOut()

        XCTAssertFalse(viewModel.isAuthenticated)
        XCTAssertFalse(viewModel.requiresEmailConfirmation)
        XCTAssertNil(viewModel.pendingConfirmationEmail, "signOut must clear the pending email so the user lands fresh on Welcome")
        XCTAssertNil(viewModel.authError)
    }

    func testSignOutFailureSetsError() async {
        mock.isAuthenticated = true
        viewModel = AuthViewModel(authService: mock)
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network error"])

        await viewModel.signOut()

        XCTAssertEqual(viewModel.authError, "Network error")
    }

    // MARK: - Initial State

    func testInitialStateReflectsAuthService() async {
        mock.isAuthenticated = true
        viewModel = AuthViewModel(authService: mock)

        XCTAssertTrue(viewModel.isAuthenticated)
    }

    func testInitialStateWhenNotAuthenticated() {
        XCTAssertFalse(viewModel.isAuthenticated)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.requiresEmailConfirmation)
        XCTAssertNil(viewModel.pendingConfirmationEmail)
        XCTAssertNil(viewModel.authError)
    }
}
