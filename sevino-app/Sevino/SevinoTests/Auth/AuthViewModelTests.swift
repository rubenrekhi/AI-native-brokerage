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

    func testSignUpFailureSetsError() async {
        mock.errorToThrow = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Email already taken"])

        await viewModel.signUp(email: "existing@test.com", password: "password123")

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
        XCTAssertNil(viewModel.authError)
    }
}
