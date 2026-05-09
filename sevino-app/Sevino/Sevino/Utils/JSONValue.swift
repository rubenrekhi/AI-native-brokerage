import Foundation

/**
 Type-safe JSON value tree.

 Used for fields whose schema is owned by another module and therefore can't
 yet be modelled with concrete `Decodable` types — e.g. the `block` payload
 inside `SSEEvent.blockStart` (the typed `Block` enum lands in C3.3).

 Sibling of `AnyCodable` but `Equatable + Sendable`, which `AnyCodable`
 cannot be (its `value: Any?` storage erases conformance). Use `JSONValue`
 when the carrier needs to ride inside an actor- or `Sendable`-bound type
 (`SSEEvent` does — it crosses actor boundaries between `SSEClient` and the
 view-model on the main actor).

 Decode order matters: integers are tried before doubles so a literal `3`
 surfaces as `.int(3)` rather than `.double(3.0)`. Foundation's
 `JSONDecoder` succeeds at decoding `3` as both, but we prefer the narrower
 type when both work — round-trip compares are friendlier that way.
 */
enum JSONValue: Decodable, Equatable, Sendable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "JSONValue could not decode the underlying JSON"
            )
        }
    }
}
