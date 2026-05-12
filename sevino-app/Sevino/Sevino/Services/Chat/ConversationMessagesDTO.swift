import Foundation

/// Wire response for `GET /v1/conversations/{id}/messages` (SEV-564).
/// Mirrors `app/schemas/conversations.py:ConversationMessagesResponse`.
/// `nextCursor` is decoded but not surfaced by the v0 resume path — one
/// page (50 messages) is enough for typical transcripts; infinite-scroll
/// is a follow-up.
struct ConversationMessagesDTO: Decodable, Sendable {
    let items: [MessageDTO]
    let nextCursor: String?
}

/// Wire shape of one persisted message. `contentBlocks` is the opaque JSONB
/// column — block-type dispatch happens in `ConversationStore.buildMessage`
/// via the existing `Block` discriminator decoder.
struct MessageDTO: Decodable, Sendable {
    let id: UUID
    let role: String
    let createdAt: Date
    let contentBlocks: [JSONValue]
}
