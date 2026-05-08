import Foundation

extension JSONDecoder {
    /// Decoder configured to match the Sevino backend's wire format.
    /// Use this in production code (`APIClient`) and tests so a strategy
    /// change in one place doesn't silently diverge from the other.
    static func sevino() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
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
