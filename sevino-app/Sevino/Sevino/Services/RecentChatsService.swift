import Foundation

/// Protocol for fetching the sidebar's "Recent chats" list — enables mocking in
/// previews and tests. Distinct from `ConversationStore`, which owns the
/// active conversation's SSE stream; this service is for the home-screen
/// drawer that lists past conversations.
protocol RecentChatsServiceProtocol: Sendable {
    func fetchRecentChats() async throws -> [ChatItem]
}

/// Real implementation backed by `GET /v1/conversations` (SEV-564). Pulls one
/// page (server-default 20) of the user's conversations sorted by recency
/// and maps the DTO into the UI `ChatItem` model. Pagination for v0 is not
/// wired through to the iOS list — one page is enough for the sidebar; the
/// `next_cursor` field is dropped here and revisited as a follow-up when
/// infinite-scroll becomes a need.
final class LiveRecentChatsService: RecentChatsServiceProtocol {
    static let shared = LiveRecentChatsService()

    private let apiClient: any APIClientProtocol

    init(apiClient: any APIClientProtocol = APIClient.shared) {
        self.apiClient = apiClient
    }

    func fetchRecentChats() async throws -> [ChatItem] {
        let response: RecentChatsResponseDTO = try await apiClient.get(
            "/v1/conversations"
        )
        return response.items.compactMap { item in
            // The backend never returns nil for `lastMessageAt` on listed
            // rows (the SQL filters out conversations with no messages),
            // but the JSON shape is permissive — fall back to omitting the
            // row rather than minting a synthetic date that breaks sort.
            guard let lastMessageAt = item.lastMessageAt else { return nil }
            return ChatItem(
                conversationId: item.id,
                title: item.title
                    ?? item.lastMessagePreview
                    ?? L10n.Sidebar.untitledConversation,
                lastMessageAt: lastMessageAt
            )
        }
    }
}

/// Canned data used by SwiftUI previews and unit tests that don't want to
/// stub the network. Production wiring uses `LiveRecentChatsService`.
final class PlaceholderRecentChatsService: RecentChatsServiceProtocol {
    static let shared = PlaceholderRecentChatsService()

    func fetchRecentChats() async throws -> [ChatItem] {
        let now = Date.now
        return [
            ChatItem(
                conversationId: UUID(),
                title: "How was Tesla's most recent e...",
                lastMessageAt: now
            ),
            ChatItem(
                conversationId: UUID(),
                title: "Help me balance my portfolio",
                lastMessageAt: now.addingTimeInterval(-300)
            ),
            ChatItem(
                conversationId: UUID(),
                title: "What happened with AMD this...",
                lastMessageAt: now.addingTimeInterval(-3600)
            ),
            ChatItem(
                conversationId: UUID(),
                title: "What is an option?",
                lastMessageAt: now.addingTimeInterval(-86400)
            ),
            ChatItem(
                conversationId: UUID(),
                title: "How much would I have made ...",
                lastMessageAt: now.addingTimeInterval(-172800)
            ),
        ]
    }
}

// MARK: - DTOs

/// Wire shape of `GET /v1/conversations`. Mirrors
/// `app/schemas/conversations.py:ConversationListResponse`. Snake_case keys
/// are mapped via the project-wide decoder (`JSONDecoder.sevino()`).
/// Internal (not file-private) so the test target can construct fixtures
/// against the same concrete type the service decodes.
struct RecentChatsResponseDTO: Decodable, Sendable {
    let items: [RecentChatItemDTO]
    let nextCursor: String?
}

struct RecentChatItemDTO: Decodable, Sendable {
    let id: UUID
    let title: String?
    let lastMessageAt: Date?
    let lastMessagePreview: String?
}
