import Foundation

/// Codes a `Date` as an ISO 8601 *string*, independent of the surrounding
/// coder's date strategy.
///
/// Chat blocks round-trip through `JSONEncoder.sevino()` during `block_data`
/// patch merges in `ConversationStore` (`mergePatch`), and that encoder leaves
/// `dateEncodingStrategy` at its `.deferredToDate` default. A bare `Date` would
/// serialize there as a numeric reference-date interval and then fail to
/// re-decode against the backend's ISO 8601 contract — silently dropping the
/// patch. Coding through a single-value `String` container (the same approach
/// `@DecimalString` takes for money) keeps the field symmetric regardless of
/// coder configuration. Decodes both fractional-second (Pydantic's
/// `…:16.704003Z`) and second-precision (`…:16Z` from Alpaca) inputs.
@propertyWrapper
struct ISO8601Date: Codable, Equatable, Hashable, Sendable {
    var wrappedValue: Date

    init(wrappedValue: Date) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let date = ISO8601Coder.parse(raw) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO 8601 date: \(raw)"
            )
        }
        self.wrappedValue = date
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(ISO8601Coder.string(from: wrappedValue))
    }
}
