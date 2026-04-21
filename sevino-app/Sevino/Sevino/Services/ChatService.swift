import Foundation

/// Protocol for fetching sidebar chat history — enables mocking in previews and tests.
protocol ChatServiceProtocol {
    func fetchRecentChats() async throws -> [ChatItem]
}

/// Placeholder implementation that returns canned chat history. This is the default
/// service used by `HomeViewModel` until the backend endpoint exists — it is
/// not a test double.
final class PlaceholderChatService: ChatServiceProtocol {
    static let shared = PlaceholderChatService()

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
