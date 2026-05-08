import Foundation

/// Response from GET /v1/brokerage/cash-interest. Mirrors
/// `app/schemas/cash_interest.py::CashInterestResponse` on the backend.
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
