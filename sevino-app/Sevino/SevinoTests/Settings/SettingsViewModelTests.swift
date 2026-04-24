import XCTest
@testable import Sevino

@MainActor
final class SettingsViewModelTests: XCTestCase {

    private var mockSettings: MockSettingsService!
    private var mockFunding: MockFundingService!
    private var viewModel: SettingsViewModel!

    override func setUp() {
        mockSettings = MockSettingsService()
        mockFunding = MockFundingService()
        viewModel = SettingsViewModel(
            settingsService: mockSettings,
            fundingService: mockFunding
        )
    }

    // MARK: - load

    func testLoadSuccessPopulatesProfileAndAccountValue() async {
        await viewModel.load()

        XCTAssertEqual(viewModel.profile?.displayName, "Riley")
        XCTAssertEqual(viewModel.accountValue?.totalValue, "$1,000.00")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadFailureSurfacesErrorAndClearsLoading() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "load failed" }
        }
        mockSettings.profileResult = .failure(LoadError())

        await viewModel.load()

        XCTAssertNil(viewModel.profile)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(viewModel.error, "load failed")
    }

    func testLoadClearsPreviousError() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "boom" }
        }
        mockSettings.profileResult = .failure(LoadError())
        await viewModel.load()
        XCTAssertNotNil(viewModel.error)

        mockSettings.profileResult = .success(
            SettingsProfileResponse(displayName: "Riley", email: nil, phoneNumber: nil, kycStatus: nil)
        )
        await viewModel.load()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - unlinkAccount

    func testUnlinkAccountSuccessTriggersReload() async {
        let id = UUID()

        await viewModel.unlinkAccount(id)

        XCTAssertEqual(mockFunding.deleteAchRelationshipCalls, [id])
        XCTAssertEqual(mockSettings.getProfileCalls, 1)
        XCTAssertEqual(mockSettings.getAccountValueCalls, 1)
        XCTAssertNotNil(viewModel.profile)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testUnlinkAccountFailureSurfacesErrorAndSkipsReload() async {
        struct UnlinkError: LocalizedError {
            var errorDescription: String? { "unlink failed" }
        }
        mockFunding.deleteAchRelationshipResult = .failure(UnlinkError())

        await viewModel.unlinkAccount(UUID())

        XCTAssertEqual(mockSettings.getProfileCalls, 0)
        XCTAssertEqual(mockSettings.getAccountValueCalls, 0)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(viewModel.error, "unlink failed")
    }

    // MARK: - clearError

    func testClearErrorResetsErrorProperty() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "boom" }
        }
        mockSettings.profileResult = .failure(LoadError())
        await viewModel.load()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }
}
