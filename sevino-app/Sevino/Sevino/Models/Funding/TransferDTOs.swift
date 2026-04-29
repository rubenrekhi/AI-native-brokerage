import Foundation

/// Body for POST /v1/funding/transfers. Field names match the backend's
/// `TransferRequest`; snake_case conversion is handled by APIClient's encoder.
///
/// `amount` is sent as a fixed-point decimal string (e.g. `"500.00"`) to match the
/// response wire format and avoid any JSON number/Double precision quirks. Pydantic
/// coerces it back to `Decimal` on the server.
struct TransferRequest: Encodable {
    let relationshipId: String
    let amount: String
    /// "INCOMING" (deposit) or "OUTGOING" (withdrawal).
    let direction: String
}

/// Response for POST /v1/funding/transfers and entries in
/// GET /v1/funding/transfers. Mirrors the backend's `TransferResponse`.
///
/// `amount` and `createdAt` are wire-format strings: the backend serializes
/// `amount` as a fixed-point string (e.g. `"500.00"`) and `createdAt` as the
/// raw Alpaca timestamp. Use `amountValue` / `createdAtDate` to coerce.
struct TransferResponse: Decodable, Identifiable, Equatable {
    let id: String
    let status: String
    let amount: String
    let direction: String
    let createdAt: String?
    let reason: String?
    let bank: TransferBank?

    var amountValue: Decimal {
        Decimal(string: amount) ?? 0
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

/// Embedded bank summary on a `TransferResponse`. Mirrors the backend's
/// `TransferBank`.
struct TransferBank: Decodable, Equatable {
    let nickname: String?
    let accountMask: String?
    let institutionName: String?
}

/// Wrapper for GET /v1/funding/transfers. Mirrors the backend's
/// `TransferListResponse`; callers of `FundingService.listTransfers()` still
/// receive a plain `[TransferResponse]`.
struct TransferListResponse: Decodable {
    let transfers: [TransferResponse]
}
