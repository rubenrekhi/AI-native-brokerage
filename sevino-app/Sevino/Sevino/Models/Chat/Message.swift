import Foundation

/**
 One turn in a conversation, owned by `ConversationStore` (C3.4).

 `blocks` is `var` because `block_data` events patch existing blocks in
 place — a stock card's price and bars arrive incrementally over the life
 of one assistant message, so the store finds the block by `blockId` and
 rebuilds it with the merged data. `id` and `role` are immutable: `id` is
 the message id assigned when the assistant message is appended on
 `turn_started`, `role` is fixed at construction time.

 Not `Codable` for v0: messages aren't decoded from a server JSON response.
 They're built up in memory from SSE events and persisted server-side via
 the agent loop, not the iOS client. Add `Codable` if/when a history fetch
 endpoint exposes them.
 */
struct Message: Identifiable, Equatable, Sendable {
    let id: UUID
    let role: Role
    var blocks: [Block]
}

enum Role: String, Codable, Equatable, Sendable {
    case user
    case assistant
}
