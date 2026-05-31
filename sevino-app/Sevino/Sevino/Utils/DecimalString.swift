import Foundation

@propertyWrapper
struct DecimalString: Codable, Equatable, Hashable {
    var wrappedValue: Decimal

    init(wrappedValue: Decimal) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let value = Decimal(string: raw) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Not a decimal string: \(raw)"
            )
        }
        self.wrappedValue = value
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode("\(wrappedValue)")
    }
}

/// Optional counterpart to `@DecimalString` for wire fields that may be null or
/// absent — e.g. the GET-only `price` / `changePct` overlay on radar rows, which
/// arrive null off the POST/PATCH paths. Decodes to nil for both a missing key
/// and an explicit JSON null; a present non-null value parses with the same
/// string→`Decimal` rule as `@DecimalString`.
@propertyWrapper
struct DecimalStringOptional: Codable, Equatable, Hashable, Sendable {
    var wrappedValue: Decimal?

    init(wrappedValue: Decimal?) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let value = Decimal(string: raw) else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Not a decimal string: \(raw)"
            )
        }
        self.wrappedValue = value
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        if let wrappedValue {
            try container.encode("\(wrappedValue)")
        } else {
            try container.encodeNil()
        }
    }
}

extension KeyedDecodingContainer {
    nonisolated func decode(
        _ type: DecimalStringOptional.Type,
        forKey key: Key
    ) throws -> DecimalStringOptional {
        try decodeIfPresent(type, forKey: key) ?? DecimalStringOptional(wrappedValue: nil)
    }
}
