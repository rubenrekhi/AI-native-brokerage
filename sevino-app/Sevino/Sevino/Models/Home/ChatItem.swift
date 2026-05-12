import Foundation

/// Sidebar row backing the recent-chats list.
///
/// `conversationId` is the backend `conversations.id` — tapping a row calls
/// `HomeViewModel.resume(conversationId:)` which swaps in a fresh
/// `ConversationStore` for that id and loads the persisted transcript.
/// `id` matches `conversationId` so `Identifiable` is stable across reloads
/// and `ForEach` doesn't churn rows when the list re-fetches.
struct ChatItem: Identifiable, Equatable, Sendable {
    let conversationId: UUID
    let title: String
    let lastMessageAt: Date

    var id: UUID { conversationId }
}
