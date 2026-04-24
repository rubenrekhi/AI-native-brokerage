import Foundation

/// Response from GET /v1/settings/profile.
/// Aggregates the user's profile, financial profile, brokerage account snapshot,
/// linked bank accounts, and sign-up timestamp.
struct SettingsProfileResponse: Decodable {
    let profile: ProfileData
    let financialProfile: FinancialProfileData?
    let brokerage: BrokerageAccountSummary?
    let linkedAccounts: [AchRelationshipDTO]
    let memberSince: String?

    /// Parsed `memberSince` timestamp. Accepts ISO-8601 with or without fractional seconds.
    var memberSinceDate: Date? {
        guard let memberSince else { return nil }
        return Self.iso8601Formatter.date(from: memberSince)
            ?? Self.iso8601FormatterNoFraction.date(from: memberSince)
    }

    private static let iso8601Formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let iso8601FormatterNoFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
}

/// Compact view of the user's Alpaca brokerage account used on the settings screen.
struct BrokerageAccountSummary: Decodable {
    let accountNumber: String?
    let accountStatus: KYCStatus
    let kycResults: [String: String]?
}

/// Response from GET /v1/settings/account-value. Amounts arrive as decimal strings
/// in the wire format and are parsed into `Decimal` at the boundary — a malformed
/// string surfaces as a `DecodingError` rather than silently becoming zero.
struct AccountValueResponse: Decodable, Equatable {
    let equity: Decimal
    let cash: Decimal
    let buyingPower: Decimal
    let portfolioValue: Decimal

    private enum CodingKeys: String, CodingKey {
        case equity, cash, buyingPower, portfolioValue
    }

    init(equity: Decimal, cash: Decimal, buyingPower: Decimal, portfolioValue: Decimal) {
        self.equity = equity
        self.cash = cash
        self.buyingPower = buyingPower
        self.portfolioValue = portfolioValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.equity = try container.decodeDecimalString(forKey: .equity)
        self.cash = try container.decodeDecimalString(forKey: .cash)
        self.buyingPower = try container.decodeDecimalString(forKey: .buyingPower)
        self.portfolioValue = try container.decodeDecimalString(forKey: .portfolioValue)
    }
}

private extension KeyedDecodingContainer {
    func decodeDecimalString(forKey key: Key) throws -> Decimal {
        let raw = try decode(String.self, forKey: key)
        guard let value = Decimal(string: raw) else {
            throw DecodingError.dataCorruptedError(
                forKey: key,
                in: self,
                debugDescription: "Expected a decimal string, got \(raw.debugDescription)"
            )
        }
        return value
    }
}

/// Response from GET /v1/settings and PATCH /v1/settings.
struct UserSettingsDTO: Decodable, Equatable {
    let theme: AppTheme
    let textSize: AppTextSize
    let notificationsEnabled: Bool
    let aiInternetAccess: Bool
}

/// Body for PATCH /v1/settings. All fields optional — only include the ones
/// being updated.
struct UserSettingsPatchRequest: Encodable, Equatable {
    var theme: AppTheme?
    var textSize: AppTextSize?
    var notificationsEnabled: Bool?
    var aiInternetAccess: Bool?
}

/// Body for PATCH /v1/settings/profile. All fields optional — only include the
/// ones being updated. `streetAddress` mirrors the onboarding wire shape where
/// the address is a list of lines.
struct ProfileUpdateRequest: Encodable, Equatable {
    var firstName: String?
    var middleName: String?
    var lastName: String?
    var preferredName: String?
    var phoneNumber: String?
    var streetAddress: [String]?
    var city: String?
    var state: String?
    var postalCode: String?
}
