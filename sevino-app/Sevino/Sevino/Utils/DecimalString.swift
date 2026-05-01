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
