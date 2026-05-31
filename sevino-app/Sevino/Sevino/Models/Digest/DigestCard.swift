import Foundation

/// Flexible wire representation of a Daily Digest card passed into chat.
///
/// The digest rendering module owns the concrete card variants. Chat only
/// needs to preserve the card object exactly enough for the backend to inject
/// it into the LLM context, so this wrapper encodes as the underlying JSON
/// object rather than as `{ "payload": ... }`.
struct DigestCard: Codable, Equatable, Sendable {
    let payload: [String: JSONValue]

    init(payload: [String: JSONValue]) {
        self.payload = payload
    }

    init(id: String, kind: String, fields: [String: JSONValue] = [:]) {
        var payload = fields
        payload["id"] = .string(id)
        payload["kind"] = .string(kind)
        self.payload = payload
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        payload = try container.decode([String: JSONValue].self)
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(payload)
    }
}
