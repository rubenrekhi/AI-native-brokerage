import Foundation

/**
 Type-erased wrapper for decoding arbitrary JSON values.

 Handles strings, numbers, bools, arrays, nested objects, and null.
 Used for dynamic fields like `APIError.detail` where the shape isn't
 known at compile time.
 */
 
struct AnyCodable: Decodable {
    let value: Any?

    init(_ value: Any?) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            value = nil
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map(\.value)
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues(\.value)
        } else {
            value = nil
        }
    }
}

extension AnyCodable {
    var stringValue: String? { value as? String }
    var intValue: Int? { value as? Int }
    var doubleValue: Double? { value as? Double }
    var boolValue: Bool? { value as? Bool }
    var arrayValue: [Any?]? { value as? [Any?] }
    var dictValue: [String: Any?]? { value as? [String: Any?] }
}
