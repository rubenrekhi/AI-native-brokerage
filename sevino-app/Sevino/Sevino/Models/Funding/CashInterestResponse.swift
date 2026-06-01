import Foundation

/// FDIC sweep enrollment state the client renders off of. Folds Alpaca account
/// status + sweep status into the four states iOS keys badge copy on.
/// Unknown wire values decode to `.unavailable` so a new backend state hides the
/// badge rather than breaking the whole response decode.
enum EnrollmentState: String, Codable {
    case active
    case pending
    case notEnrolled = "not_enrolled"
    case unavailable

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = EnrollmentState(rawValue: raw) ?? .unavailable
    }
}

/// Response from GET /v1/brokerage/cash-interest.
///
/// Monetary values are wire-format string decimals (matches `AccountValueResponse`)
/// and are converted to `Decimal` by the ViewModel. `apy` is a decimal fraction
/// (e.g. "0.0425" = 4.25%).
struct CashInterestResponse: Decodable, Equatable {
    let balance: String
    let apy: String
    let thisMonthEarned: String
    let daysAccrued: Int
    let lifetimeEarned: String
    let lifetimeSince: String?
    let buyingPower: String
    let pendingDeposits: String
    let interestPaidOut: String
    let fdicInsuredLimit: String
    let sweepStatus: String?
    let enrollmentState: EnrollmentState?

    /// Pydantic emits `2025-10-01T00:00:00+00:00` (no fractional seconds) but
    /// other timestamps in the codebase carry microseconds — accept both.
    var lifetimeSinceDate: Date? {
        guard let lifetimeSince else { return nil }
        return Self.iso8601Formatter.date(from: lifetimeSince)
            ?? Self.iso8601FormatterNoFraction.date(from: lifetimeSince)
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
