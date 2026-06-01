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

    func testSaveAddressSendsAllFieldsTrimmed() async {
        await viewModel.saveAddress(
            street: ["  123 Main St  ", "Apt 4"],
            city: "  Cleveland ",
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

    func testSaveAddressDropsBlankStreetLines() async {
        await viewModel.saveAddress(
            street: ["123 Main St", "   "],
            city: "Cleveland",
            state: "OH",
            postalCode: "44110"
        )

        let request = service.updateProfileCalls[0]
        XCTAssertEqual(request.streetAddress, ["123 Main St"])
    }

    func testSaveAddressRejectsMissingRequiredField() async {
        await viewModel.saveAddress(
            street: ["123 Main St"],
            city: "",
            state: "OH",
            postalCode: "44110"
        )

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editAddressMissingFieldError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
    }

    func testSaveAddressRejectsAllBlankStreetLines() async {
        await viewModel.saveAddress(
            street: ["   ", ""],
            city: "Cleveland",
            state: "OH",
            postalCode: "44110"
        )

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editAddressMissingFieldError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
    }

    func testSaveAddressRejectsNonUSState() async {
        await viewModel.saveAddress(
            street: ["123 Main St"],
            city: "Toronto",
            state: "ON",
            postalCode: "M5H 2N2"
        )

        XCTAssertFalse(viewModel.didSave)
        XCTAssertEqual(viewModel.error, L10n.Settings.editAddressNonUSError)
        XCTAssertEqual(service.updateProfileCalls.count, 0)
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
        await viewModel.savePhone("123")
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
