import Foundation

/// ISO 8601 timestamp coding for the Sevino wire format.
///
/// Backend timestamps arrive as strings in two precisions: fractional-second
/// (Pydantic's default `2026-05-11T22:14:16.704003Z`) and second-precision
/// (`2026-05-11T22:14:16Z` from upstream Alpaca). `parse` accepts either;
/// `string(from:)` emits fractional precision. The stock `.iso8601` strategy
/// only accepts the second-precision form.
enum ISO8601Coder {
    static func parse(_ raw: String) -> Date? {
        fractional.date(from: raw) ?? plain.date(from: raw)
    }

    static func string(from date: Date) -> String {
        fractional.string(from: date)
    }

    private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
