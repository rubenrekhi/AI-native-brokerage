import Foundation

/// Property-wrapper companion to `@DecimalString` for wire fields that carry an
/// ISO 8601 timestamp as a JSON string. Decodes either a fractional-second
/// (`2026-06-14T00:00:00.000Z`) or second-precision (`2026-06-14T00:00:00Z`)
/// string — matching `JSONDecoder.sevino()` — and always re-encodes at second
/// precision.
///
/// The wrapper exists so wire dates survive a `JSONEncoder.sevino()` round trip:
/// that encoder leaves `dateEncodingStrategy` at the default `.deferredToDate`,
/// which emits a numeric date the string-expecting Sevino decoder would reject.
/// Routing the date through a string here keeps `Block` round-trips stable
/// without coupling a block to the coder's date strategy.
@propertyWrapper
struct ISO8601DateString: Codable, Equatable, Hashable, Sendable {
    var wrappedValue: Date

    init(wrappedValue: Date) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let date = _iso8601StringDate(raw) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Not an ISO 8601 date string: \(raw)"
            )
        }
        self.wrappedValue = date
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(_iso8601String.string(from: wrappedValue))
    }
}

private func _iso8601StringDate(_ raw: String) -> Date? {
    _iso8601StringFractional.date(from: raw) ?? _iso8601String.date(from: raw)
}

private let _iso8601String: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f
}()

private let _iso8601StringFractional: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()
