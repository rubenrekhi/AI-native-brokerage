import Foundation

extension JSONDecoder {
    /// Decoder configured to match the Sevino backend's wire format.
    /// Use this in production code (`APIClient`) and tests so a strategy
    /// change in one place doesn't silently diverge from the other.
    ///
    /// The date strategy accepts both fractional-second (Pydantic's default
    /// `2026-05-11T22:14:16.704003Z`) and second-precision
    /// (`2026-05-11T22:14:16Z` from upstream Alpaca payloads) ISO 8601
    /// strings — the stock `.iso8601` strategy only accepts the latter.
    static func sevino() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            guard let date = ISO8601Coder.parse(raw) else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Invalid ISO 8601 date: \(raw)"
                )
            }
            return date
        }
        return decoder
    }
}

extension JSONEncoder {
    static func sevino() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}
