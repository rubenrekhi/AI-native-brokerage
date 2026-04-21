import Foundation
@testable import Sevino

final class MockChatService: ChatServiceProtocol {
    var fetchRecentChatsError: Error?
    var chats: [ChatItem] = []

    private(set) var fetchRecentChatsCallCount = 0

    func fetchRecentChats() async throws -> [ChatItem] {
        fetchRecentChatsCallCount += 1
        if let error = fetchRecentChatsError { throw error }
        return chats
    }
}
