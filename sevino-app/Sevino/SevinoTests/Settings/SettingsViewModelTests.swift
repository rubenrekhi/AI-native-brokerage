import XCTest
@testable import Sevino

@MainActor
final class SettingsViewModelTests: XCTestCase {

    private var mockSettings: MockSettingsService!
    private var mockFunding: MockFundingService!
    private var viewModel: SettingsViewModel!

    override func setUp() {
        mockSettings = MockSettingsService()
        mockSettings.getProfileResult = .success(Self.stubProfile())
        mockSettings.getAccountValueResult = .success(Self.stubAccountValue())
        mockFunding = MockFundingService()
        viewModel = SettingsViewModel(
            settingsService: mockSettings,
            fundingService: mockFunding
        )
    }

    // MARK: - load

    func testLoadSuccessPopulatesProfileAndAccountValue() async {
        await viewModel.load()

        XCTAssertEqual(viewModel.profile?.profile.preferredName, "Riley")
        XCTAssertEqual(viewModel.accountValue?.equity, Decimal(string: "1000.00"))
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadFailureSurfacesErrorAndClearsLoading() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "load failed" }
        }
        mockSettings.getProfileResult = .failure(LoadError())

        await viewModel.load()

        XCTAssertNil(viewModel.profile)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(viewModel.error, "load failed")
    }

    func testLoadClearsPreviousError() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "boom" }
        }
        mockSettings.getProfileResult = .failure(LoadError())
        await viewModel.load()
        XCTAssertNotNil(viewModel.error)

        mockSettings.getProfileResult = .success(Self.stubProfile())
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
        mockSettings.getProfileResult = .failure(LoadError())
        await viewModel.load()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Fixtures

    private static func stubProfile() -> SettingsProfileResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = Data(#"""
        {
          "profile": { "preferred_name": "Riley", "first_name": "Riley" },
          "financial_profile": null,
          "brokerage": null,
          "linked_accounts": [],
          "member_since": null
        }
        """#.utf8)
        // swiftlint:disable:next force_try
        return try! decoder.decode(SettingsProfileResponse.self, from: json)
    }

    private static func stubAccountValue() -> AccountValueResponse {
        AccountValueResponse(
            equity: Decimal(string: "1000.00") ?? 0,
            cash: Decimal(string: "500.00") ?? 0,
            buyingPower: Decimal(string: "2000.00") ?? 0,
            portfolioValue: Decimal(string: "1500.00") ?? 0
        )
    }
}
