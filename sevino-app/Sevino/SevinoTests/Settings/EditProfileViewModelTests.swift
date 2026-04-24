import XCTest
@testable import Sevino

@MainActor
final class EditProfileViewModelTests: XCTestCase {

    private var service: MockSettingsService!
    private var viewModel: EditProfileViewModel!

    override func setUp() {
        super.setUp()
        service = MockSettingsService()
        service.updateProfileResult = .success(Self.stubProfileResponse)
        viewModel = EditProfileViewModel(service: service)
    }

    func testInitialState() {
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.didSave)
        XCTAssertNil(viewModel.error)
    }

    func testSaveNameSendsTrimmedFieldsWithoutEmptyMiddle() async {
        await viewModel.saveName(first: "  Riley  ", middle: nil, last: " Ready ")

        XCTAssertTrue(viewModel.didSave)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(service.updateProfileCalls.count, 1)
        let request = service.updateProfileCalls[0]
        XCTAssertEqual(request.firstName, "Riley")
        XCTAssertEqual(request.lastName, "Ready")
        XCTAssertNil(request.middleName)
        XCTAssertNil(request.phoneNumber)
        XCTAssertNil(request.streetAddress)
    }

    func testSaveNameIncludesMiddleWhenProvided() async {
        await viewModel.saveName(first: "Riley", middle: "James", last: "Ready")

        let request = service.updateProfileCalls[0]
        XCTAssertEqual(request.middleName, "James")
    }

    func testSaveNameRejectsEmptyFirstNameWithoutCallingService() async {
        await viewModel.saveName(first: "   ", middle: nil, last: "Ready")

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editNameValidationError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
    }

    func testSaveNameRejectsEmptyLastNameWithoutCallingService() async {
        await viewModel.saveName(first: "Riley", middle: nil, last: "")

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editNameValidationError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
    }

    func testSavePhoneSendsTrimmedPhone() async {
        await viewModel.savePhone("  +1 (555) 123-4567  ")

        XCTAssertTrue(viewModel.didSave)
        let request = service.updateProfileCalls[0]
        XCTAssertEqual(request.phoneNumber, "+1 (555) 123-4567")
        XCTAssertNil(request.firstName)
    }

    func testSavePhoneRejectsTooFewDigits() async {
        await viewModel.savePhone("123")

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editPhoneValidationError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
    }

    func testSaveAddressSendsAllFields() async {
        await viewModel.saveAddress(
            street: ["123 Main St", "Apt 4"],
            city: "Cleveland",
            state: "OH",
            postalCode: "44110"
        )

        XCTAssertTrue(viewModel.didSave)
        let request = service.updateProfileCalls[0]
        XCTAssertEqual(request.streetAddress, ["123 Main St", "Apt 4"])
        XCTAssertEqual(request.city, "Cleveland")
        XCTAssertEqual(request.state, "OH")
        XCTAssertEqual(request.postalCode, "44110")
        XCTAssertNil(request.firstName)
        XCTAssertNil(request.phoneNumber)
    }

    func testServiceErrorSurfacesAsLocalizedDescription() async {
        struct ServiceError: LocalizedError {
            var errorDescription: String? { "Backend said no" }
        }
        service.updateProfileResult = .failure(ServiceError())

        await viewModel.savePhone("5551234567")

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, "Backend said no")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testSaveResetsPriorDidSaveBeforeRetry() async {
        await viewModel.savePhone("5551234567")
        XCTAssertTrue(viewModel.didSave)

        struct ServiceError: LocalizedError {
            var errorDescription: String? { "Fail" }
        }
        service.updateProfileResult = .failure(ServiceError())

        await viewModel.savePhone("5551234567")

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, "Fail")
    }

    func testClearErrorResetsError() async {
        await viewModel.saveName(first: "", middle: nil, last: "Ready")
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()
        XCTAssertNil(viewModel.error)
    }

    func testIsValidPhoneAcceptsTenDigitsAndE164() {
        XCTAssertTrue(EditProfileViewModel.isValidPhone("5551234567"))
        XCTAssertTrue(EditProfileViewModel.isValidPhone("(555) 123-4567"))
        XCTAssertTrue(EditProfileViewModel.isValidPhone("+1 555 123 4567"))
        XCTAssertFalse(EditProfileViewModel.isValidPhone("12345"))
        XCTAssertFalse(EditProfileViewModel.isValidPhone(""))
    }

    // MARK: - Fixtures

    private static let stubProfileResponse: SettingsProfileResponse = {
        let json = Data("""
        {
          "profile": {
            "first_name": "Riley",
            "last_name": "Ready",
            "email": "riley@sevino.ai"
          },
          "financial_profile": null,
          "brokerage": null,
          "linked_accounts": [],
          "member_since": null
        }
        """.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // swiftlint:disable:next force_try
        return try! decoder.decode(SettingsProfileResponse.self, from: json)
    }()
}
