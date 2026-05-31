import Foundation

struct DividendResponse: Decodable, Identifiable, Equatable {
    let id: String
    let symbol: String
    let netAmount: String
    let status: String
    let createdAt: String?

    var netAmountValue: Decimal {
        Decimal(string: netAmount) ?? 0
    }

    var createdAtDate: Date? {
        guard let createdAt else { return nil }
        return Self.iso8601Formatter.date(from: createdAt)
            ?? Self.iso8601FormatterNoFraction.date(from: createdAt)
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

struct DividendListResponse: Decodable {
    let dividends: [DividendResponse]
}

/// `correct` is Alpaca's "adjustment to a prior dividend" record — still a
/// money-in event, so it groups with `executed` under `settled`.
enum DividendStatusKind: Equatable {
    case settled
    case pending
    case failed
    case unknown

    static func from(_ status: String) -> DividendStatusKind {
        switch status.lowercased() {
        case "executed", "correct": return .settled
        case "canceled", "cancelled": return .failed
        default: return .unknown
        }
    }
}
