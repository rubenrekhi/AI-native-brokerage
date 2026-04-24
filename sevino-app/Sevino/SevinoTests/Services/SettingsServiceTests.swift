import XCTest
@testable import Sevino

final class SettingsServiceTests: XCTestCase {

    private var api: MockAPIClient!
    private var service: SettingsService!

    override func setUp() {
        super.setUp()
        api = MockAPIClient()
        service = SettingsService(api: api)
    }

    override func tearDown() {
        api = nil
        service = nil
        super.tearDown()
    }

    // MARK: - getProfile

    func test_getProfile_callsCorrectPath() async throws {
        api.responseToReturn = Self.stubProfile()

        _ = try await service.getProfile()

        XCTAssertEqual(api.lastPath, "/v1/settings/profile")
        XCTAssertEqual(api.lastMethod, "GET")
    }

    func test_getProfile_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates { try await self.service.getProfile() }
    }

    // MARK: - getAccountValue

    func test_getAccountValue_callsCorrectPath() async throws {
        api.responseToReturn = Self.stubAccountValue()

        _ = try await service.getAccountValue()

        XCTAssertEqual(api.lastPath, "/v1/settings/account-value")
        XCTAssertEqual(api.lastMethod, "GET")
    }

    func test_getAccountValue_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates { try await self.service.getAccountValue() }
    }

    // MARK: - getSettings

    func test_getSettings_callsCorrectPath() async throws {
        api.responseToReturn = Self.stubSettings()

        _ = try await service.getSettings()

        XCTAssertEqual(api.lastPath, "/v1/settings")
        XCTAssertEqual(api.lastMethod, "GET")
    }

    func test_getSettings_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates { try await self.service.getSettings() }
    }

    // MARK: - updateSettings

    func test_updateSettings_sendsPatchWithBody() async throws {
        api.responseToReturn = Self.stubSettings()
        let request = UserSettingsPatchRequest(
            theme: .dark,
            textSize: nil,
            notificationsEnabled: nil,
            aiInternetAccess: nil
        )

        _ = try await service.updateSettings(request)

        XCTAssertEqual(api.lastPath, "/v1/settings")
        XCTAssertEqual(api.lastMethod, "PATCH")
        XCTAssertEqual(api.lastBody as? UserSettingsPatchRequest, request)
    }

    func test_updateSettings_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates {
            try await self.service.updateSettings(UserSettingsPatchRequest())
        }
    }

    // MARK: - updateProfile

    func test_updateProfile_sendsPatchWithBody() async throws {
        api.responseToReturn = Self.stubProfile()
        let request = ProfileUpdateRequest(preferredName: "Riley")

        _ = try await service.updateProfile(request)

        XCTAssertEqual(api.lastPath, "/v1/settings/profile")
        XCTAssertEqual(api.lastMethod, "PATCH")
        XCTAssertEqual(api.lastBody as? ProfileUpdateRequest, request)
    }

    func test_updateProfile_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates {
            try await self.service.updateProfile(ProfileUpdateRequest())
        }
    }

    // MARK: - deleteAccount

    func test_deleteAccount_callsDelete() async throws {
        try await service.deleteAccount()

        XCTAssertEqual(api.lastPath, "/v1/settings/account")
        XCTAssertEqual(api.lastMethod, "DELETE")
    }

    func test_deleteAccount_propagatesError() async {
        api.errorToThrow = TestError()
        await assertPropagates { try await self.service.deleteAccount() }
    }

    // MARK: - Helpers

    private struct TestError: Error, Equatable {}

    private func assertPropagates<T>(
        _ call: () async throws -> T,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            _ = try await call()
            XCTFail("expected error to propagate", file: file, line: line)
        } catch is TestError {
            // expected
        } catch {
            XCTFail("unexpected error: \(error)", file: file, line: line)
        }
    }

    private static func stubProfile() -> SettingsProfileResponse {
        decode(SettingsProfileResponse.self, from: #"""
        {
          "profile": { "preferred_name": "Riley", "first_name": "Riley" },
          "financial_profile": null,
          "brokerage": null,
          "linked_accounts": [],
          "member_since": null
        }
        """#)
    }

    private static func stubAccountValue() -> AccountValueResponse {
        AccountValueResponse(
            equity: Decimal(string: "1000.00") ?? 0,
            cash: Decimal(string: "500.00") ?? 0,
            buyingPower: Decimal(string: "2000.00") ?? 0,
            portfolioValue: Decimal(string: "1500.00") ?? 0
        )
    }

    private static func stubSettings() -> UserSettingsDTO {
        decode(UserSettingsDTO.self, from: #"""
        {"theme":"system","text_size":"regular","notifications_enabled":true,"ai_internet_access":false}
        """#)
    }

    private static func decode<T: Decodable>(_ type: T.Type, from json: String) -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // swiftlint:disable:next force_try
        return try! decoder.decode(T.self, from: Data(json.utf8))
    }
}
