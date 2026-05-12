import XCTest
@testable import Sevino

/**
 Tests for `LiveRecentChatsService` (SEV-564).

 The service maps the `GET /v1/conversations` wire response into the UI
 `ChatItem` model. Coverage focuses on the title-fallback chain, dropping
 rows with `nil` lastMessageAt, and the request path.
 */
final class LiveRecentChatsServiceTests: XCTestCase {

    private var api: MockAPIClient!

    override func setUp() {
        api = MockAPIClient()
    }

    private func decodeFixture(_ json: String) throws -> Any {
        try JSONDecoder.sevino().decode(
            RecentChatsResponseDTO.self, from: Data(json.utf8)
        )
    }

    func testHitsExpectedPath() async throws {
        api.responseToReturn = try decodeFixture(
            #"{"items": [], "next_cursor": null}"#
        )
        let service = LiveRecentChatsService(apiClient: api)

        _ = try await service.fetchRecentChats()

        XCTAssertEqual(api.lastPath, "/v1/conversations")
        XCTAssertEqual(api.lastMethod, "GET")
    }

    func testEmptyResponseProducesEmptyList() async throws {
        api.responseToReturn = try decodeFixture(
            #"{"items": [], "next_cursor": null}"#
        )
        let service = LiveRecentChatsService(apiClient: api)

        let chats = try await service.fetchRecentChats()

        XCTAssertEqual(chats.count, 0)
    }

    func testPrefersTitleOverPreview() async throws {
        let id = UUID()
        let json = """
        {
          "items": [
            {
              "id": "\(id.uuidString)",
              "title": "How is AAPL?",
              "last_message_at": "2026-05-11T20:00:00Z",
              "last_message_preview": "Apple Inc. is …"
            }
          ],
          "next_cursor": null
        }
        """
        api.responseToReturn = try decodeFixture(json)
        let service = LiveRecentChatsService(apiClient: api)

        let chats = try await service.fetchRecentChats()

        XCTAssertEqual(chats.count, 1)
        XCTAssertEqual(chats[0].conversationId, id)
        XCTAssertEqual(chats[0].title, "How is AAPL?")
    }

    func testFallsBackToPreviewWhenTitleIsNil() async throws {
        let id = UUID()
        let json = """
        {
          "items": [
            {
              "id": "\(id.uuidString)",
              "title": null,
              "last_message_at": "2026-05-11T20:00:00Z",
              "last_message_preview": "Hello there"
            }
          ],
          "next_cursor": null
        }
        """
        api.responseToReturn = try decodeFixture(json)
        let service = LiveRecentChatsService(apiClient: api)

        let chats = try await service.fetchRecentChats()

        XCTAssertEqual(chats[0].title, "Hello there")
    }

    func testFallsBackToLocalizedFallbackWhenBothNil() async throws {
        let id = UUID()
        let json = """
        {
          "items": [
            {
              "id": "\(id.uuidString)",
              "title": null,
              "last_message_at": "2026-05-11T20:00:00Z",
              "last_message_preview": null
            }
          ],
          "next_cursor": null
        }
        """
        api.responseToReturn = try decodeFixture(json)
        let service = LiveRecentChatsService(apiClient: api)

        let chats = try await service.fetchRecentChats()

        XCTAssertEqual(chats[0].title, L10n.Sidebar.untitledConversation)
    }

    func testDropsRowsWithNilLastMessageAt() async throws {
        // The backend filters NULL lastMessageAt server-side, but the wire
        // shape is permissive; the service drops such rows defensively.
        let json = """
        {
          "items": [
            {
              "id": "\(UUID().uuidString)",
              "title": "Real one",
              "last_message_at": "2026-05-11T20:00:00Z",
              "last_message_preview": null
            },
            {
              "id": "\(UUID().uuidString)",
              "title": "Ghost",
              "last_message_at": null,
              "last_message_preview": null
            }
          ],
          "next_cursor": null
        }
        """
        api.responseToReturn = try decodeFixture(json)
        let service = LiveRecentChatsService(apiClient: api)

        let chats = try await service.fetchRecentChats()

        XCTAssertEqual(chats.count, 1)
        XCTAssertEqual(chats[0].title, "Real one")
    }

    func testRethrowsTransportError() async {
        api.errorToThrow = URLError(.notConnectedToInternet)
        let service = LiveRecentChatsService(apiClient: api)

        do {
            _ = try await service.fetchRecentChats()
            XCTFail("expected fetch to rethrow transport error")
        } catch {
            XCTAssertNotNil(error as? URLError)
        }
    }
}

