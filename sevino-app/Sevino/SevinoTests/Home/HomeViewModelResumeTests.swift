import XCTest
@testable import Sevino

/**
 Tests for `HomeViewModel.resume(conversationId:)` (SEV-564).

 Resume swaps the active `ConversationStore` for one bound to the chosen
 conversation id and loads the persisted transcript. The chat surface
 keys off `isConversationActive` (true when `messages` is non-empty) so
 the overlay renders the loaded history.
 */
@MainActor
final class HomeViewModelResumeTests: XCTestCase {

    private var mockProfile: MockUserProfileService!
    private var mockChat: MockRecentChatsService!

    override func setUp() {
        mockProfile = MockUserProfileService()
        mockChat = MockRecentChatsService()
    }

    func testResumeSwapsStoreAndLoadsTranscript() async throws {
        let conversationId = UUID(uuidString: "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")!
        let json = """
        {
          "items": [
            {
              "id": "\(UUID().uuidString)",
              "role": "user",
              "created_at": "2026-05-11T20:00:00Z",
              "content_blocks": [
                {"type": "text", "block_id": "u1", "text": "How is AAPL?"}
              ]
            },
            {
              "id": "\(UUID().uuidString)",
              "role": "assistant",
              "created_at": "2026-05-11T20:00:01Z",
              "content_blocks": [
                {"type": "text", "block_id": "a1", "text": "Apple is …"}
              ]
            }
          ],
          "next_cursor": null
        }
        """
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = try JSONDecoder.sevino().decode(
            ConversationMessagesDTO.self, from: Data(json.utf8)
        )
        let initialStore = ConversationStore(
            conversationId: UUID(),
            sseClient: MockSSEClient(),
            baseURL: "https://api.example.com",
            apiClient: MockAPIClient()
        )
        let viewModel = HomeViewModel(
            userProfileService: mockProfile,
            chatService: mockChat,
            conversationStore: initialStore,
            conversationStoreFactory: { id in
                ConversationStore(
                    conversationId: id,
                    sseClient: MockSSEClient(),
                    baseURL: "https://api.example.com",
                    apiClient: mockAPI
                )
            }
        )

        XCTAssertFalse(viewModel.isConversationActive, "starts inactive")

        await viewModel.resume(conversationId: conversationId)

        XCTAssertNotIdentical(viewModel.conversationStore, initialStore)
        XCTAssertEqual(viewModel.conversationStore.conversationId, conversationId)
        XCTAssertEqual(viewModel.messages.count, 2)
        XCTAssertTrue(viewModel.isConversationActive, "non-empty transcript flips active")
        XCTAssertNil(viewModel.resumeError, "happy path leaves no error")
    }

    func testResumeFailureSurfacesResumeError() async {
        // Acceptance criterion: the failed load is surfaced on the view
        // model as `resumeError` (not silently swallowed). Closing the
        // sidebar without feedback was the issue auditors flagged.
        let mockAPI = MockAPIClient()
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)
        let initialStore = ConversationStore(
            conversationId: UUID(),
            sseClient: MockSSEClient(),
            baseURL: "https://api.example.com",
            apiClient: MockAPIClient()
        )
        let viewModel = HomeViewModel(
            userProfileService: mockProfile,
            chatService: mockChat,
            conversationStore: initialStore,
            conversationStoreFactory: { id in
                ConversationStore(
                    conversationId: id,
                    sseClient: MockSSEClient(),
                    baseURL: "https://api.example.com",
                    apiClient: mockAPI
                )
            }
        )

        let conversationId = UUID()
        await viewModel.resume(conversationId: conversationId)

        XCTAssertNotIdentical(viewModel.conversationStore, initialStore)
        XCTAssertEqual(viewModel.conversationStore.conversationId, conversationId)
        XCTAssertFalse(viewModel.isConversationActive, "no transcript on failed load")
        XCTAssertNotNil(viewModel.resumeError, "failure must surface to the view")
    }

    func testClearResumeErrorResetsError() async {
        let mockAPI = MockAPIClient()
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)
        let viewModel = HomeViewModel(
            userProfileService: mockProfile,
            chatService: mockChat,
            conversationStoreFactory: { id in
                ConversationStore(
                    conversationId: id,
                    sseClient: MockSSEClient(),
                    baseURL: "https://api.example.com",
                    apiClient: mockAPI
                )
            }
        )
        await viewModel.resume(conversationId: UUID())
        XCTAssertNotNil(viewModel.resumeError)

        viewModel.clearResumeError()
        XCTAssertNil(viewModel.resumeError)
    }

    func testSendAfterResumeRoutesToTheResumedStore() async throws {
        // Resume swaps the store; a subsequent send must hit the *new*
        // store's SSE client, not the original one. Without this guard a
        // resume could leave stale routing where send still went to the
        // pre-resume conversation id.
        let json = #"{"items": [], "next_cursor": null}"#
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = try JSONDecoder.sevino().decode(
            ConversationMessagesDTO.self, from: Data(json.utf8)
        )
        let initialSSE = MockSSEClient()
        let resumedSSE = MockSSEClient(script: [
            .yield(MockSSEClient.makeRaw(json: """
                {"id":"01TS","type":"turn_started","turn_id":"\(UUID().uuidString)","conversation_id":"\(UUID().uuidString)"}
            """)),
            .yield(MockSSEClient.makeRaw(json: """
                {"id":"01TC","type":"turn_completed","turn_id":"\(UUID().uuidString)","terminal_state":"end_turn","total_cost_usd_micros":0,"iterations_count":1}
            """)),
        ])
        let initialStore = ConversationStore(
            conversationId: UUID(),
            sseClient: initialSSE,
            baseURL: "https://api.example.com",
            apiClient: MockAPIClient()
        )
        let viewModel = HomeViewModel(
            userProfileService: mockProfile,
            chatService: mockChat,
            conversationStore: initialStore,
            conversationStoreFactory: { id in
                ConversationStore(
                    conversationId: id,
                    sseClient: resumedSSE,
                    baseURL: "https://api.example.com",
                    apiClient: mockAPI
                )
            }
        )

        await viewModel.resume(conversationId: UUID())
        try await viewModel.send(text: "follow-up")

        XCTAssertEqual(
            initialSSE.capturedRequests.count,
            0,
            "send after resume must not touch the original store's SSE client"
        )
        XCTAssertEqual(
            resumedSSE.capturedRequests.count,
            1,
            "send after resume hits the resumed store"
        )
    }
}
