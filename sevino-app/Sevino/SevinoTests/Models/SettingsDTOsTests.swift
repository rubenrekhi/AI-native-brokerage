import XCTest
@testable import Sevino

final class SettingsDTOsTests: XCTestCase {

    // MARK: - AccountValueResponse

    func testAccountValueResponseDecodesDecimalStrings() throws {
        let json = Data(#"""
        {"equity":"1234.56","cash":"78.90","buying_power":"2469.12","portfolio_value":"1500.25"}
        """#.utf8)

        let response = try Self.makeDecoder().decode(AccountValueResponse.self, from: json)

        XCTAssertEqual(response.equity, Decimal(string: "1234.56"))
        XCTAssertEqual(response.cash, Decimal(string: "78.90"))
        XCTAssertEqual(response.buyingPower, Decimal(string: "2469.12"))
        XCTAssertEqual(response.portfolioValue, Decimal(string: "1500.25"))
    }

    func testAccountValueResponseThrowsOnMalformedDecimal() {
        let json = Data(#"""
        {"equity":"not-a-number","cash":"0","buying_power":"0","portfolio_value":"0"}
        """#.utf8)

        XCTAssertThrowsError(
            try Self.makeDecoder().decode(AccountValueResponse.self, from: json)
        ) { error in
            guard case DecodingError.dataCorrupted = error else {
                XCTFail("expected DecodingError.dataCorrupted, got \(error)")
                return
            }
        }
    }

    // MARK: - SettingsProfileResponse.memberSinceDate

    func testMemberSinceDateParsesIso8601WithFractionalSeconds() throws {
        let profile = try Self.decodeProfile(memberSince: "2026-04-24T12:34:56.789Z")

        let expected = ISO8601DateFormatter.withFractionalSeconds.date(from: "2026-04-24T12:34:56.789Z")
        XCTAssertEqual(profile.memberSinceDate, expected)
    }

    func testMemberSinceDateParsesIso8601WithoutFractionalSeconds() throws {
        let profile = try Self.decodeProfile(memberSince: "2026-04-24T12:34:56Z")

        let expected = ISO8601DateFormatter().date(from: "2026-04-24T12:34:56Z")
        XCTAssertEqual(profile.memberSinceDate, expected)
    }

    func testMemberSinceDateIsNilWhenMissing() throws {
        let profile = try Self.decodeProfile(memberSince: nil)

        XCTAssertNil(profile.memberSinceDate)
    }

    // MARK: - UserSettingsDTO

    func testUserSettingsDecodesEnumFields() throws {
        let json = Data(#"""
        {"theme":"dark","text_size":"small","notifications_enabled":false,"ai_internet_access":true}
        """#.utf8)

        let settings = try Self.makeDecoder().decode(UserSettingsDTO.self, from: json)

        XCTAssertEqual(settings.theme, .dark)
        XCTAssertEqual(settings.textSize, .small)
        XCTAssertFalse(settings.notificationsEnabled)
        XCTAssertTrue(settings.aiInternetAccess)
    }

    // MARK: - Helpers

    private static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private static func decodeProfile(memberSince: String?) throws -> SettingsProfileResponse {
        let memberSinceField = memberSince.map { "\"\($0)\"" } ?? "null"
        let json = Data(#"""
        {
          "profile": { "preferred_name": "Riley", "first_name": "Riley" },
          "financial_profile": null,
          "brokerage": null,
          "linked_accounts": [],
          "member_since": \#(memberSinceField)
        }
        """#.utf8)
        return try makeDecoder().decode(SettingsProfileResponse.self, from: json)
    }
}

private extension ISO8601DateFormatter {
    static let withFractionalSeconds: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
