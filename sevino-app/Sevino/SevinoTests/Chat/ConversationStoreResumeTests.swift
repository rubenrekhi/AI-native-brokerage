import XCTest
@testable import Sevino

/**
 Tests for `ConversationStore.load()` (SEV-564) — the resume path that
 hydrates a fresh store with a persisted transcript from
 `GET /v1/conversations/{id}/messages`.

 The store decodes the JSONB-shaped `content_blocks` column into the same
 `Block` discriminated union used at runtime, so a resumed conversation
 renders through the same view path as a live turn. These tests pin down
 the decoding contract.
 */
@MainActor
final class ConversationStoreResumeTests: XCTestCase {

    private let conversationId = UUID(uuidString: "11111111-2222-3333-4444-555555555555")!

    // MARK: - Happy path

    func testLoadPopulatesMessagesFromPersistedBlocks() async throws {
        let userMessageId = UUID()
        let assistantMessageId = UUID()
        let json = """
        {
          "items": [
            {
              "id": "\(userMessageId.uuidString)",
              "role": "user",
              "created_at": "2026-05-11T20:00:00Z",
              "content_blocks": [
                {"type": "text", "block_id": "u1", "text": "What is AAPL?"}
              ]
            },
            {
              "id": "\(assistantMessageId.uuidString)",
              "role": "assistant",
              "created_at": "2026-05-11T20:00:01Z",
              "content_blocks": [
                {"type": "text", "block_id": "a1", "text": "Apple Inc. is …"}
              ]
            }
          ],
          "next_cursor": null
        }
        """
        let api = MockAPIClient()
        api.responseToReturn = try decodeDTO(from: json)

        let store = makeStore(api: api)
        try await store.load()

        XCTAssertEqual(api.lastPath, "/v1/conversations/\(conversationId.uuidString.lowercased())/messages")
        XCTAssertEqual(api.lastMethod, "GET")
        XCTAssertEqual(store.messages.count, 2)

        let user = store.messages[0]
        XCTAssertEqual(user.id, userMessageId)
        XCTAssertEqual(user.role, Role.user)
        guard case .text(let userText) = user.blocks.first else {
            return XCTFail("expected user text block")
        }
        XCTAssertEqual(userText.text, "What is AAPL?")

        let assistant = store.messages[1]
        XCTAssertEqual(assistant.id, assistantMessageId)
        XCTAssertEqual(assistant.role, Role.assistant)
        guard case .text(let assistantText) = assistant.blocks.first else {
            return XCTFail("expected assistant text block")
        }
        XCTAssertEqual(assistantText.text, "Apple Inc. is …")

        XCTAssertEqual(store.state, .idle)
    }

    func testLoadOnEmptyConversationLeavesMessagesEmpty() async throws {
        let api = MockAPIClient()
        api.responseToReturn = try decodeDTO(
            from: #"{"items": [], "next_cursor": null}"#
        )

        let store = makeStore(api: api)
        try await store.load()

        XCTAssertEqual(store.messages.count, 0)
        XCTAssertEqual(store.state, .idle)
    }

    // MARK: - Forward-compatibility

    func testUnknownBlockTypesAreDroppedNotCrashed() async throws {
        // The wire schema is open by design: a future block variant lands
        // on persisted assistant messages, but old iOS clients have no
        // decoder for it. Verify the unknown block is logged and dropped
        // while the rest of the message survives. ``future_widget`` is
        // not in the discriminated union — pick any type that isn't (was
        // ``thinking`` before SEV-571 added the real variant).
        let json = """
        {
          "items": [
            {
              "id": "\(UUID().uuidString)",
              "role": "assistant",
              "created_at": "2026-05-11T20:00:00Z",
              "content_blocks": [
                {"type": "future_widget", "block_id": "t1", "summary": "ignore me"},
                {"type": "text", "block_id": "a1", "text": "real reply"}
              ]
            }
          ],
          "next_cursor": null
        }
        """
        let api = MockAPIClient()
        api.responseToReturn = try decodeDTO(from: json)

        let store = makeStore(api: api)
        try await store.load()

        XCTAssertEqual(store.messages.count, 1)
        XCTAssertEqual(store.messages[0].blocks.count, 1, "unknown block dropped, text kept")
        guard case .text(let text) = store.messages[0].blocks[0] else {
            return XCTFail("expected text block to survive")
        }
        XCTAssertEqual(text.text, "real reply")
    }

    // MARK: - Error path

    func testLoadFailureParksStateInErrorAndRethrows() async {
        let api = MockAPIClient()
        api.errorToThrow = URLError(.notConnectedToInternet)

        let store = makeStore(api: api)
        do {
            try await store.load()
            XCTFail("expected load() to rethrow transport error")
        } catch {
            XCTAssertNotNil(error as? URLError)
        }

        if case .error(let code, _) = store.state {
            XCTAssertEqual(code, .internalError)
        } else {
            XCTFail("expected error state, got \(store.state)")
        }
        XCTAssertEqual(store.messages.count, 0)
    }

    // MARK: - Helpers

    private func makeStore(api: any APIClientProtocol) -> ConversationStore {
        ConversationStore(
            conversationId: conversationId,
            sseClient: MockSSEClient(),
            baseURL: "https://api.example.com",
            idempotencyKeyFactory: { "k" },
            apiClient: api
        )
    }

    private func decodeDTO(from json: String) throws -> ConversationMessagesDTO {
        let data = Data(json.utf8)
        return try JSONDecoder.sevino().decode(ConversationMessagesDTO.self, from: data)
    }
}
