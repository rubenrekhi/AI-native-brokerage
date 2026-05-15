import Foundation
@testable import Sevino

final class MockRecentChatsService: RecentChatsServiceProtocol {
    var fetchRecentChatsError: Error?
    var chats: [ChatItem] = []

    private(set) var fetchRecentChatsCallCount = 0

    func fetchRecentChats() async throws -> [ChatItem] {
        fetchRecentChatsCallCount += 1
        if let error = fetchRecentChatsError { throw error }
        return chats
    }

    var deleteConversationError: Error?
    private(set) var deletedConversationIds: [UUID] = []

    func deleteConversation(_ id: UUID) async throws {
        deletedConversationIds.append(id)
        if let error = deleteConversationError { throw error }
    }
}
