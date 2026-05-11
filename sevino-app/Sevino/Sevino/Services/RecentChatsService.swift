import Foundation

/// Protocol for fetching the sidebar's "Recent chats" list — enables mocking in
/// previews and tests. Distinct from `ConversationStore`, which owns the
/// active conversation's SSE stream; this service is for the home-screen
/// drawer that lists past conversations.
protocol RecentChatsServiceProtocol {
    func fetchRecentChats() async throws -> [ChatItem]
}

/// Hardcoded canned data backing the recent-chats sidebar until the backend
/// `GET /v1/conversations` endpoint exists. Listed in the AI v0 plan as
/// post-v0 work (see "Conversation list UI / GET endpoint" in the Appendix
/// of `sevino-api/docs/ai-v0-plan.md`).
final class PlaceholderRecentChatsService: RecentChatsServiceProtocol {
    static let shared = PlaceholderRecentChatsService()

    func fetchRecentChats() async throws -> [ChatItem] {
        [
            ChatItem(title: "How was Tesla's most recent e..."),
            ChatItem(title: "Help me balance my portfolio"),
            ChatItem(title: "What happened with AMD this..."),
            ChatItem(title: "What is an option?"),
            ChatItem(title: "How much would I have made ..."),
        ]
    }
}
