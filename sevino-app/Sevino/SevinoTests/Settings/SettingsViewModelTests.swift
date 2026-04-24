import XCTest
@testable import Sevino

@MainActor
final class SettingsViewModelTests: XCTestCase {

    private var mockSettings: MockSettingsService!
    private var mockFunding: MockFundingService!
    private var mockAuth: MockAuthService!
    private var viewModel: SettingsViewModel!

    override func setUp() {
        mockSettings = MockSettingsService()
        mockSettings.getProfileResult = .success(Self.stubProfile())
        mockSettings.getAccountValueResult = .success(Self.stubAccountValue())
        mockFunding = MockFundingService()
        mockAuth = MockAuthService()
        viewModel = SettingsViewModel(
            settingsService: mockSettings,
            fundingService: mockFunding,
            authService: mockAuth
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

    // MARK: - deleteAccount

    func testDeleteAccountSuccessSignsOut() async {
        mockAuth.isAuthenticated = true

        await viewModel.deleteAccount()

        XCTAssertEqual(mockSettings.deleteAccountCalls, 1)
        XCTAssertEqual(mockAuth.signOutCalls, 1)
        XCTAssertFalse(viewModel.isDeletingAccount)
        XCTAssertNil(viewModel.deleteError)
        XCTAssertFalse(viewModel.showDeleteError)
    }

    func testDeleteAccountFailureSkipsSignOutAndSurfacesError() async {
        struct DeleteError: LocalizedError {
            var errorDescription: String? { "cannot delete — open positions" }
        }
        mockSettings.deleteAccountResult = .failure(DeleteError())

        await viewModel.deleteAccount()

        XCTAssertEqual(mockSettings.deleteAccountCalls, 1)
        XCTAssertEqual(mockAuth.signOutCalls, 0)
        XCTAssertFalse(viewModel.isDeletingAccount)
        XCTAssertEqual(viewModel.deleteError, "cannot delete — open positions")
        XCTAssertTrue(viewModel.showDeleteError)
        // Unrelated `error` channel stays clear so sibling screens aren't affected.
        XCTAssertNil(viewModel.error)
    }

    func testDeleteAccountSwallowsSignOutFailure() async {
        // After a successful server-side delete the account is gone, so a
        // subsequent sign-out failure must not surface — the app should proceed
        // to the unauthenticated state without a misleading error alert.
        struct SignOutError: LocalizedError {
            var errorDescription: String? { "session refresh failed" }
        }
        mockAuth.isAuthenticated = true
        mockAuth.signOutError = SignOutError()

        await viewModel.deleteAccount()

        XCTAssertEqual(mockSettings.deleteAccountCalls, 1)
        XCTAssertEqual(mockAuth.signOutCalls, 1)
        XCTAssertFalse(viewModel.isDeletingAccount)
        XCTAssertNil(viewModel.deleteError)
        XCTAssertNil(viewModel.error)
    }

    func testShowDeleteErrorBindingDismissClearsError() async {
        struct DeleteError: LocalizedError {
            var errorDescription: String? { "boom" }
        }
        mockSettings.deleteAccountResult = .failure(DeleteError())
        await viewModel.deleteAccount()
        XCTAssertTrue(viewModel.showDeleteError)

        // Simulate the alert dismissing itself via its isPresented binding.
        viewModel.showDeleteError = false

        XCTAssertNil(viewModel.deleteError)
        XCTAssertFalse(viewModel.showDeleteError)
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

    // MARK: - Derived display fields

    func testDisplayFieldsUsePlaceholderWhenProfileMissing() {
        XCTAssertEqual(viewModel.displayName, L10n.Settings.missingValuePlaceholder)
        XCTAssertEqual(viewModel.displayEmail, L10n.Settings.missingValuePlaceholder)
        XCTAssertEqual(viewModel.displayPhone, L10n.Settings.missingValuePlaceholder)
        XCTAssertEqual(viewModel.displayAddress, L10n.Settings.missingValuePlaceholder)
        XCTAssertEqual(viewModel.displayRiskTolerance, L10n.Settings.missingValuePlaceholder)
        XCTAssertNil(viewModel.displayMemberDuration)
    }

    func testDisplayNamePrefersPreferredName() async {
        mockSettings.getProfileResult = .success(Self.stubProfile(preferred: "Rye", first: "Riley", last: "Ready"))
        await viewModel.load()

        XCTAssertEqual(viewModel.displayName, "Rye")
    }

    func testDisplayNameFallsBackToFirstAndLast() async {
        mockSettings.getProfileResult = .success(Self.stubProfile(preferred: nil, first: "Riley", last: "Ready"))
        await viewModel.load()

        XCTAssertEqual(viewModel.displayName, "Riley Ready")
    }

    func testDisplayInitialsUsesUpToTwoInitials() async {
        mockSettings.getProfileResult = .success(Self.stubProfile(preferred: "Ready Riley Rose", first: nil, last: nil))
        await viewModel.load()

        XCTAssertEqual(viewModel.displayInitials, "RR")
    }

    func testDisplayAddressComposesLinesAndOmitsMissingSegments() async {
        mockSettings.getProfileResult = .success(Self.stubProfile(
            streetLines: ["123 Main St", ""],
            city: "Cleveland",
            state: nil,
            postal: "44110"
        ))
        await viewModel.load()

        XCTAssertEqual(viewModel.displayAddress, "123 Main St, Cleveland, 44110")
    }

    // MARK: - formatPhone

    func testFormatPhoneFormatsUSNumbers() {
        XCTAssertEqual(SettingsViewModel.formatPhone("+11234567890"), "+1 (123) 456 7890")
        XCTAssertEqual(SettingsViewModel.formatPhone("1234567890"), "(123) 456 7890")
    }

    func testFormatPhonePassesThroughUnrecognizedFormats() {
        XCTAssertEqual(SettingsViewModel.formatPhone("+44 20 7946 0958"), "+44 20 7946 0958")
    }

    func testFormatPhoneReturnsPlaceholderForEmpty() {
        XCTAssertEqual(SettingsViewModel.formatPhone(nil), L10n.Settings.missingValuePlaceholder)
        XCTAssertEqual(SettingsViewModel.formatPhone(""), L10n.Settings.missingValuePlaceholder)
    }

    // MARK: - riskToleranceLabel

    func testRiskToleranceAggressiveWhenBuyingMoreAndHighLoss() {
        let label = SettingsViewModel.riskToleranceLabel(maxLoss: "40%+", scenario: "buy_more")
        XCTAssertEqual(label, L10n.Settings.riskAggressive)
    }

    func testRiskToleranceConservativeWhenLowLoss() {
        let label = SettingsViewModel.riskToleranceLabel(maxLoss: "0-5%", scenario: "sell")
        XCTAssertEqual(label, L10n.Settings.riskConservative)
    }

    func testRiskToleranceModerateDefaultForMidScenarios() {
        let label = SettingsViewModel.riskToleranceLabel(maxLoss: "15-25%", scenario: "hold")
        XCTAssertEqual(label, L10n.Settings.riskModerate)
    }

    func testRiskToleranceNilWhenBothInputsMissing() {
        XCTAssertNil(SettingsViewModel.riskToleranceLabel(maxLoss: nil, scenario: nil))
        XCTAssertNil(SettingsViewModel.riskToleranceLabel(maxLoss: "", scenario: ""))
    }

    func testRiskToleranceAcceptsRawUILabels() {
        // The DB stores whatever the user picked during onboarding, which may
        // be the UI label form rather than the canonical enum.
        let label = SettingsViewModel.riskToleranceLabel(
            maxLoss: "25 – 40% decline",
            scenario: "Hold and do nothing — Wait for recovery"
        )
        XCTAssertEqual(label, L10n.Settings.riskModerate)

        let aggressive = SettingsViewModel.riskToleranceLabel(
            maxLoss: "40%+",
            scenario: "Buy more and capitalize on the dip"
        )
        XCTAssertEqual(aggressive, L10n.Settings.riskAggressive)
    }

    // MARK: - formatMemberDuration

    func testFormatMemberDurationReturnsNoneForNegativeRange() {
        let end = Date(timeIntervalSince1970: 0)
        let start = Date(timeIntervalSince1970: 86_400)
        XCTAssertEqual(
            SettingsViewModel.formatMemberDuration(from: start, to: end, calendar: .current),
            L10n.Settings.durationNone
        )
    }

    func testFormatMemberDurationReturnsNoneWhenIdentical() {
        let d = Date(timeIntervalSince1970: 1_700_000_000)
        XCTAssertEqual(
            SettingsViewModel.formatMemberDuration(from: d, to: d, calendar: .current),
            L10n.Settings.durationNone
        )
    }

    func testFormatMemberDurationIncludesMonthsWeeksDays() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let start = calendar.date(from: DateComponents(year: 2026, month: 1, day: 1))!
        // Expect 3 months, 1 week, 2 days -> April 10, 2026
        let end = calendar.date(from: DateComponents(year: 2026, month: 4, day: 10))!

        let result = SettingsViewModel.formatMemberDuration(from: start, to: end, calendar: calendar)

        XCTAssertTrue(result.contains("3"))
        XCTAssertTrue(result.contains("1"))
        XCTAssertTrue(result.contains("2"))
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

    private static func stubProfile(
        preferred: String?,
        first: String?,
        last: String?
    ) -> SettingsProfileResponse {
        stubProfile(
            preferred: preferred,
            first: first,
            last: last,
            streetLines: nil,
            city: nil,
            state: nil,
            postal: nil
        )
    }

    private static func stubProfile(
        streetLines: [String]?,
        city: String?,
        state: String?,
        postal: String?
    ) -> SettingsProfileResponse {
        stubProfile(
            preferred: "Riley",
            first: nil,
            last: nil,
            streetLines: streetLines,
            city: city,
            state: state,
            postal: postal
        )
    }

    private static func stubProfile(
        preferred: String?,
        first: String?,
        last: String?,
        streetLines: [String]?,
        city: String?,
        state: String?,
        postal: String?
    ) -> SettingsProfileResponse {
        var profile: [String: Any] = [:]
        if let preferred { profile["preferred_name"] = preferred }
        if let first { profile["first_name"] = first }
        if let last { profile["last_name"] = last }
        if let streetLines { profile["street_address"] = streetLines }
        if let city { profile["city"] = city }
        if let state { profile["state"] = state }
        if let postal { profile["postal_code"] = postal }

        let payload: [String: Any] = [
            "profile": profile,
            "financial_profile": NSNull(),
            "brokerage": NSNull(),
            "linked_accounts": [],
            "member_since": NSNull()
        ]
        // swiftlint:disable:next force_try
        let data = try! JSONSerialization.data(withJSONObject: payload)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // swiftlint:disable:next force_try
        return try! decoder.decode(SettingsProfileResponse.self, from: data)
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
