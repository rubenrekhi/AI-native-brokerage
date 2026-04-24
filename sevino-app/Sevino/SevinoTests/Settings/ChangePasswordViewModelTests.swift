import XCTest
@testable import Sevino

@MainActor
final class ChangePasswordViewModelTests: XCTestCase {

    private var mock: MockAuthService!
    private var viewModel: ChangePasswordViewModel!

    override func setUp() {
        mock = MockAuthService()
        viewModel = ChangePasswordViewModel(authService: mock)
    }

    func testInitialState() {
        XCTAssertEqual(viewModel.currentPassword, "")
        XCTAssertEqual(viewModel.newPassword, "")
        XCTAssertEqual(viewModel.confirmPassword, "")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.didSucceed)
        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.isValid)
    }

    func testIsValidRequiresMatchingPasswordsThatMeetRequirements() {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "NewStrong1!"
        XCTAssertTrue(viewModel.passwordsMatch)
        XCTAssertTrue(viewModel.meetsRequirements)
        XCTAssertTrue(viewModel.isValid)
    }

    func testIsInvalidWhenPasswordsDoNotMatch() {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "Different1!"
        XCTAssertFalse(viewModel.passwordsMatch)
        XCTAssertFalse(viewModel.isValid)
    }

    func testIsInvalidWhenNewPasswordMissingRequirement() {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "weakpass"
        viewModel.confirmPassword = "weakpass"
        XCTAssertFalse(viewModel.meetsRequirements)
        XCTAssertFalse(viewModel.isValid)
    }

    func testChangePasswordSuccess() async {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "NewStrong1!"

        await viewModel.changePassword()

        XCTAssertTrue(viewModel.didSucceed)
        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(mock.updatePasswordCallCount, 1)
        XCTAssertEqual(mock.lastCurrentPassword, "Current1!")
        XCTAssertEqual(mock.lastUpdatedPassword, "NewStrong1!")
    }

    func testChangePasswordMapsPasswordChangeErrorToLocalizedDescription() async {
        viewModel.currentPassword = "Wrong1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "NewStrong1!"
        mock.errorToThrow = PasswordChangeError.incorrectCurrentPassword

        await viewModel.changePassword()

        XCTAssertFalse(viewModel.didSucceed)
        XCTAssertEqual(viewModel.error, L10n.Settings.currentPasswordIncorrectError)
    }

    func testChangePasswordUnknownErrorUsesGenericLocalizedMessage() async {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "NewStrong1!"
        mock.errorToThrow = NSError(
            domain: "SupabaseGoTrue",
            code: 0,
            userInfo: [NSLocalizedDescriptionKey: "JWT expired"]
        )

        await viewModel.changePassword()

        XCTAssertFalse(viewModel.didSucceed)
        XCTAssertEqual(viewModel.error, L10n.Settings.changePasswordGenericError)
        XCTAssertFalse(viewModel.isLoading)
    }

    func testChangePasswordRejectsWeakPasswordWithoutCallingService() async {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "weakpass"
        viewModel.confirmPassword = "weakpass"

        await viewModel.changePassword()

        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.didSucceed)
        XCTAssertEqual(mock.updatePasswordCallCount, 0)
    }

    func testChangePasswordRejectsMismatchWithoutCallingService() async {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "NewStrong1!"
        viewModel.confirmPassword = "Different1!"

        await viewModel.changePassword()

        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.didSucceed)
        XCTAssertEqual(mock.updatePasswordCallCount, 0)
    }

    func testClearErrorResetsError() async {
        viewModel.currentPassword = "Current1!"
        viewModel.newPassword = "weakpass"
        viewModel.confirmPassword = "weakpass"
        await viewModel.changePassword()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()
        XCTAssertNil(viewModel.error)
    }
}
