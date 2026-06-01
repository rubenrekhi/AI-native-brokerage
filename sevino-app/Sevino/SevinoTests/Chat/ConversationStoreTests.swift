import XCTest
@testable import Sevino

/**
 Acceptance tests for `ConversationStore` (SEV-506 / C3.4).

 The store owns the SSE-event-to-message-list translation; these tests pin
 down the shape of that translation by feeding scripted event sequences
 through `MockSSEClient` and asserting the resulting `messages` array,
 `state`, and `currentTurnId`.
 */
@MainActor
final class ConversationStoreTests: XCTestCase {

    private static let testBaseURL = "https://api.example.com"

    private let conversationId = UUID(uuidString: "11111111-2222-3333-4444-555555555555")!
    private let turnId = UUID(uuidString: "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")!
    private let secondTurnId = UUID(uuidString: "BBBBBBBB-CCCC-DDDD-EEEE-FFFFFFFFFFFF")!

    // MARK: - Happy path

    func testFullTurnAppendsUserAndAssistantMessages() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "b1"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: "Hello"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: " world"))),
            .yield(makeRaw(json: blockEndJSON(blockId: "b1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client, idempotencyKey: "fixed-key")

        try await store.send(text: "say hi")

        XCTAssertEqual(store.messages.count, 2, "user message + assistant message")

        // User message
        XCTAssertEqual(store.messages[0].role, .user)
        guard case .text(let userText) = store.messages[0].blocks.first else {
            return XCTFail("expected user message to have a text block")
        }
        XCTAssertEqual(userText.text, "say hi")

        // Assistant message
        XCTAssertEqual(store.messages[1].role, .assistant)
        XCTAssertEqual(store.messages[1].blocks.count, 1)
        guard case .text(let assistantText) = store.messages[1].blocks[0] else {
            return XCTFail("expected assistant message to have a text block")
        }
        XCTAssertEqual(assistantText.blockId, "b1")
        XCTAssertEqual(assistantText.text, "Hello world")

        XCTAssertEqual(store.state, .idle)
        // Acceptance criterion: currentTurnId clears after the turn so a stale
        // id can't leak into the next request.
        XCTAssertNil(store.currentTurnId)
    }

    func testMultipleBlocksPreserveOrder() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartStatusJSON(blockId: "s1", label: "Searching", state: "active"))),
            .yield(makeRaw(json: blockDataJSON(blockId: "s1", patch: ["state": "complete"]))),
            .yield(makeRaw(json: blockEndJSON(blockId: "s1"))),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "t1"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "t1", text: "AMD is up"))),
            .yield(makeRaw(json: blockEndJSON(blockId: "t1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)

        try await store.send(text: "how is AMD")

        let assistant = store.messages[1]
        XCTAssertEqual(assistant.blocks.count, 2)

        guard case .status(let status) = assistant.blocks[0] else {
            return XCTFail("expected first block to be .status")
        }
        XCTAssertEqual(status.label, "Searching")
        XCTAssertEqual(status.state, .complete, "block_data patch should flip state to complete")

        guard case .text(let text) = assistant.blocks[1] else {
            return XCTFail("expected second block to be .text")
        }
        XCTAssertEqual(text.text, "AMD is up")
    }

    func testBlockDataPatchMergesIntoStockCard() async throws {
        // Stock card arrives empty, then a `block_data` patch fills in price
        // and bars — exercises the last-write-wins per-key merge.
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: emptyStockCardBlockStartJSON(blockId: "card1"))),
            .yield(makeRaw(json: blockDataJSON(
                blockId: "card1",
                patch: [
                    "price": 184.92,
                    "change_abs": 2.12,
                    "change_pct": 0.0116,
                    "color_state": "positive",
                    "bars": [
                        ["t": "2026-04-29T13:30:00Z", "c": 184.92] as [String: Any]
                    ],
                ]
            ))),
            .yield(makeRaw(json: blockEndJSON(blockId: "card1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)

        try await store.send(text: "amd?")

        guard case .stockCard(let card) = store.messages[1].blocks[0] else {
            return XCTFail("expected stock card block")
        }
        XCTAssertEqual(card.symbol, "AMD", "patch must not clobber unspecified keys")
        XCTAssertEqual(card.price, 184.92, accuracy: 1e-6)
        XCTAssertEqual(card.changeAbs, 2.12, accuracy: 1e-6)
        XCTAssertEqual(card.colorState, .positive)
        XCTAssertEqual(card.bars.count, 1)
        XCTAssertEqual(card.bars[0].c, 184.92, accuracy: 1e-6)
    }

    // MARK: - Sequential turns

    func testSequentialSendsAccumulateMessages() async throws {
        // Two consecutive successful turns on the same store should leave 4
        // messages (user/assistant × 2) and reset state to idle between them.
        let client = MockSSEClient(scripts: [
            [
                .yield(makeRaw(json: turnStartedJSON())),
                .yield(makeRaw(json: blockStartTextJSON(blockId: "b1"))),
                .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: "first"))),
                .yield(makeRaw(json: blockEndJSON(blockId: "b1"))),
                .yield(makeRaw(json: turnCompletedJSON())),
            ],
            [
                .yield(makeRaw(json: turnStartedJSON(turnId: secondTurnId))),
                .yield(makeRaw(json: blockStartTextJSON(blockId: "b2"))),
                .yield(makeRaw(json: textDeltaJSON(blockId: "b2", text: "second"))),
                .yield(makeRaw(json: blockEndJSON(blockId: "b2"))),
                .yield(makeRaw(json: turnCompletedJSON(turnId: secondTurnId))),
            ],
        ])
        let store = makeStore(client: client)

        try await store.send(text: "one")
        XCTAssertEqual(store.messages.count, 2)
        XCTAssertEqual(store.state, .idle)

        try await store.send(text: "two")

        XCTAssertEqual(store.messages.count, 4, "two complete turns should produce four messages")
        XCTAssertEqual(store.state, .idle)
        XCTAssertNil(store.currentTurnId)

        guard case .text(let firstAssistant) = store.messages[1].blocks.first,
              case .text(let secondAssistant) = store.messages[3].blocks.first else {
            return XCTFail("expected text blocks on both assistant turns")
        }
        XCTAssertEqual(firstAssistant.text, "first")
        XCTAssertEqual(secondAssistant.text, "second")
        XCTAssertEqual(client.capturedRequests.count, 2, "each send opens its own stream")
    }

    // MARK: - Optimistic user message

    func testUserMessageIsAppendedBeforeAnyEvent() async throws {
        // Use awaitCancellation so the SSE stream parks indefinitely after the
        // user message lands. We can then inspect `messages` without racing
        // with the event loop, then cancel to clean up.
        let client = MockSSEClient(script: [.awaitCancellation])
        let store = makeStore(client: client)

        let task = Task { try await store.send(text: "hello") }
        await waitFor { store.messages.count == 1 && store.state == .streaming }

        XCTAssertEqual(store.messages.count, 1)
        XCTAssertEqual(store.messages[0].role, .user)
        XCTAssertEqual(store.state, .streaming)

        task.cancel()
        _ = try? await task.value
    }

    // MARK: - Error handling

    func testErrorEventFlipsStateToError() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "b1"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: "partial"))),
            .yield(makeRaw(json: errorJSON(code: "model_rate_limit", message: "429 from upstream"))),
        ])
        let store = makeStore(client: client)

        try await store.send(text: "go")

        XCTAssertEqual(store.state, .error(.modelRateLimit, "429 from upstream"))
        // Partial assistant message is preserved so the user sees what they
        // got before the error.
        XCTAssertEqual(store.messages.count, 2)
        guard case .text(let block) = store.messages[1].blocks[0] else {
            return XCTFail("expected partial text block to survive the error")
        }
        XCTAssertEqual(block.text, "partial")
    }

    func testTransportErrorBeforeStreamSurfacesAsErrorState() async {
        // SSEClient throws before any event arrives — common case is HTTP 401
        // surfacing as `SSEClientError.httpStatus(401)`.
        let client = MockSSEClient(script: [.fail(SSEClientError.httpStatus(401))])
        let store = makeStore(client: client)

        do {
            try await store.send(text: "go")
            XCTFail("expected send() to rethrow transport error")
        } catch {
            XCTAssertEqual(error as? SSEClientError, .httpStatus(401))
        }

        if case .error(let code, _) = store.state {
            XCTAssertEqual(code, .internalError, "transport errors map to .internalError")
        } else {
            XCTFail("expected state to be .error, got \(store.state)")
        }
        // User message is still present — the optimistic append happens before
        // the network call, so a failed turn shows the user's message in the
        // history.
        XCTAssertEqual(store.messages.count, 1)
        XCTAssertEqual(store.messages[0].role, .user)
    }

    // MARK: - Defensive merge handling

    func testTextDeltaForUnknownBlockIdIsIgnored() async throws {
        // The store should log and skip rather than throwing when a `text_delta`
        // names a block that hasn't started — wire-contract violations must not
        // tear down the whole turn.
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "real"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "ghost", text: "should be ignored"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "real", text: "kept"))),
            .yield(makeRaw(json: blockEndJSON(blockId: "real"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)

        try await store.send(text: "hi")

        XCTAssertEqual(store.state, .idle, "unknown block_id should not flip state to error")
        guard case .text(let block) = store.messages[1].blocks[0] else {
            return XCTFail("expected text block")
        }
        XCTAssertEqual(block.text, "kept", "real block survives, ghost delta dropped silently")
    }

    func testNonObjectBlockDataPatchIsIgnored() async throws {
        // The wire format models `data` as an object patch; a non-object payload
        // (e.g. a raw string) is malformed. The store logs and skips so a single
        // bad patch doesn't terminate the turn.
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "b1"))),
            .yield(makeRaw(json: """
                {"id":"01BD","type":"block_data","block_id":"b1","data":"not an object"}
                """)),
            .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: "still good"))),
            .yield(makeRaw(json: blockEndJSON(blockId: "b1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)

        try await store.send(text: "hi")

        XCTAssertEqual(store.state, .idle)
        guard case .text(let block) = store.messages[1].blocks[0] else {
            return XCTFail("expected text block")
        }
        XCTAssertEqual(block.text, "still good")
    }

    // MARK: - Cancellation

    func testCancellationClosesStreamCleanlyAndResetsState() async {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .awaitCancellation,
        ])
        let store = makeStore(client: client)

        let task = Task { try await store.send(text: "hi") }
        // Allow turn_started to land so we know send() is mid-stream.
        await waitFor { store.currentTurnId != nil }

        task.cancel()
        do {
            try await task.value
            XCTFail("expected cancelled task to throw")
        } catch is CancellationError {
            // Expected
        } catch {
            XCTFail("expected CancellationError, got \(error)")
        }

        XCTAssertEqual(store.state, .idle, "cancel should reset state to idle")
    }

    // MARK: - Request shape

    func testSendBuildsCorrectRequest() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client, idempotencyKey: "idem-fixed-key")

        try await store.send(text: "hello there")

        XCTAssertEqual(client.capturedRequests.count, 1)
        let request = client.capturedRequests[0]
        XCTAssertEqual(
            request.url?.absoluteString,
            "\(Self.testBaseURL)/v1/conversations/\(conversationId.uuidString.lowercased())/turns"
        )
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")

        let body = try XCTUnwrap(request.httpBody)
        let decoded = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        XCTAssertEqual(decoded?["message"] as? String, "hello there")
        XCTAssertEqual(decoded?["idempotency_key"] as? String, "idem-fixed-key")
        XCTAssertNil(decoded?["context"])
        XCTAssertNil(decoded?["digest_card"])
        XCTAssertEqual(decoded?["client_timezone"] as? String, "America/New_York")
    }

    func testSendRoutesDigestCardThroughContext() async throws {
        // SEV-615 B: a digest card rides the unified `context` channel as
        // `kind=digest` (payload becomes the opaque `data`); there is no
        // separate `digest_card` field.
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client, idempotencyKey: "digest-key")
        let digestCard = ChatDigestCard(
            id: "digest-1",
            kind: "big_move",
            fields: [
                "camelCaseKey": .string("preserved"),
                "relatedSymbols": .array([.string("NVDA")]),
                "related_symbols": .array([.string("AMD")]),
                "card_context": .object(["headline": .string("AMD moved 5%")]),
            ]
        )

        try await store.send(text: "what changed?", digestCard: digestCard)

        let body = try XCTUnwrap(client.capturedRequests[0].httpBody)
        let decoded = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        XCTAssertNil(decoded?["digest_card"])

        let context = try XCTUnwrap(decoded?["context"] as? [String: Any])
        XCTAssertEqual(context["kind"] as? String, "digest")

        // The card payload becomes `data`, with keys preserved verbatim
        // (no snake_case mangling of the opaque bag).
        let data = try XCTUnwrap(context["data"] as? [String: Any])
        XCTAssertEqual(data["id"] as? String, "digest-1")
        XCTAssertEqual(data["kind"] as? String, "big_move")
        XCTAssertEqual(data["camelCaseKey"] as? String, "preserved")
        XCTAssertNil(data["camel_case_key"])
        XCTAssertEqual(data["relatedSymbols"] as? [String], ["NVDA"])
        XCTAssertEqual(data["related_symbols"] as? [String], ["AMD"])

        let cardContext = try XCTUnwrap(data["card_context"] as? [String: Any])
        XCTAssertEqual(cardContext["headline"] as? String, "AMD moved 5%")
    }

    func testDigestCardAddsSourceToUserMessage() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "b1"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "b1", text: "Reading the card."))),
            .yield(makeRaw(json: blockEndJSON(blockId: "b1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)
        let digestCard = ChatDigestCard(
            id: "digest-1",
            kind: "earnings_result",
            fields: ["related_symbols": .array([.string("AAPL")])]
        )

        try await store.send(text: "what matters?", digestCard: digestCard)

        XCTAssertEqual(
            store.messages[0].cardContextSource,
            CardContextSource(symbol: "AAPL", kind: "earnings_result")
        )
        XCTAssertNil(store.messages[1].cardContextSource)
    }

    func testTurnStartedCardContextSourceOverridesDigestFallback() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON(cardContextSource: #"{"symbol":"MSFT","kind":"news"}"#))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)
        let digestCard = ChatDigestCard(
            id: "digest-1",
            kind: "earnings_result",
            fields: ["related_symbols": .array([.string("AAPL")])]
        )

        try await store.send(text: "what matters?", digestCard: digestCard)

        XCTAssertEqual(
            store.messages[0].cardContextSource,
            CardContextSource(symbol: "MSFT", kind: "news")
        )
    }

    func testExplicitIdempotencyKeyOverridesFactory() async throws {
        // Retry callers pass an explicit key so the backend's idempotency slot
        // replays the persisted result. Verify the override beats the factory.
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client, idempotencyKey: "factory-key")

        try await store.send(text: "retry me", idempotencyKey: "explicit-retry-key")

        let body = try XCTUnwrap(client.capturedRequests[0].httpBody)
        let decoded = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        XCTAssertEqual(decoded?["idempotency_key"] as? String, "explicit-retry-key")
    }

    func testCurrentTurnIdIsSetMidTurn() async {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .awaitCancellation,
        ])
        let store = makeStore(client: client)

        let task = Task { try await store.send(text: "hi") }
        await waitFor { store.currentTurnId != nil }
        XCTAssertEqual(store.currentTurnId, turnId)

        task.cancel()
        _ = try? await task.value
    }

    // MARK: - submitAction (HIL confirm/reject)

    func testSubmitActionPostsDecisionAndStreamsResult() async throws {
        let client = MockSSEClient(script: [
            .yield(makeRaw(json: turnStartedJSON())),
            .yield(makeRaw(json: blockStartTextJSON(blockId: "n1"))),
            .yield(makeRaw(json: textDeltaJSON(blockId: "n1", text: "Done"))),
            .yield(makeRaw(json: blockEndJSON(blockId: "n1"))),
            .yield(makeRaw(json: blockStartConfirmationJSON(
                blockId: "r1", actionId: "act-123", status: "executed"
            ))),
            .yield(makeRaw(json: blockEndJSON(blockId: "r1"))),
            .yield(makeRaw(json: turnCompletedJSON())),
        ])
        let store = makeStore(client: client)

        try await store.submitAction(actionId: "act-123", decision: "confirm")

        XCTAssertEqual(client.capturedRequests.count, 1)
        let request = client.capturedRequests[0]
        XCTAssertEqual(
            request.url?.absoluteString,
            "\(Self.testBaseURL)/v1/conversations/\(conversationId.uuidString.lowercased())/actions/act-123"
        )
        XCTAssertEqual(request.httpMethod, "POST")
        let body = try XCTUnwrap(request.httpBody)
        let decoded = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        XCTAssertEqual(decoded?["decision"] as? String, "confirm")

        // No user bubble; the result streams into one assistant message.
        XCTAssertEqual(store.messages.count, 1)
        XCTAssertEqual(store.messages[0].role, .assistant)
        XCTAssertEqual(store.messages[0].blocks.count, 2)
        XCTAssertEqual(store.state, .idle)
    }

    func testSendSupersedesPendingConfirmationCard() async throws {
        let client = MockSSEClient(scripts: [
            [
                .yield(makeRaw(json: turnStartedJSON())),
                .yield(makeRaw(json: blockStartConfirmationJSON(
                    blockId: "c1", actionId: "a1", status: "pending"
                ))),
                .yield(makeRaw(json: blockEndJSON(blockId: "c1"))),
                .yield(makeRaw(json: turnCompletedJSON())),
            ],
            [
                .yield(makeRaw(json: turnStartedJSON())),
                .yield(makeRaw(json: blockStartTextJSON(blockId: "t1"))),
                .yield(makeRaw(json: textDeltaJSON(blockId: "t1", text: "ok"))),
                .yield(makeRaw(json: blockEndJSON(blockId: "t1"))),
                .yield(makeRaw(json: turnCompletedJSON())),
            ],
        ])
        let store = makeStore(client: client)

        try await store.send(text: "deposit 500")
        guard case .confirmation(let card)? = store.messages[1].blocks.first
        else {
            return XCTFail("expected a pending confirmation card")
        }
        XCTAssertTrue(card.isPending)

        try await store.send(text: "actually never mind")
        guard case .confirmation(let after)? = store.messages[1].blocks.first
        else {
            return XCTFail("confirmation card should still be present")
        }
        XCTAssertEqual(after.status, "superseded")
        XCTAssertFalse(after.isPending)
    }

    // MARK: - Helpers

    private func makeStore(
        client: any SSEClientProtocol,
        idempotencyKey: String = "k",
        timeZoneIdentifier: String = "America/New_York"
    ) -> ConversationStore {
        ConversationStore(
            conversationId: conversationId,
            sseClient: client,
            baseURL: Self.testBaseURL,
            idempotencyKeyFactory: { idempotencyKey },
            timeZoneIdentifierProvider: { timeZoneIdentifier }
        )
    }

    /// Yield the main actor up to `iterations` times, breaking early when
    /// `condition()` returns true. Drives the SSE consumer's scheduling
    /// without sleeping, which would race against the simulator's load.
    private func waitFor(
        iterations: Int = 30,
        _ condition: () -> Bool
    ) async {
        for _ in 0..<iterations {
            if condition() { return }
            await Task.yield()
        }
    }

    // MARK: - JSON fixtures

    private func turnStartedJSON(turnId: UUID? = nil, cardContextSource: String? = nil) -> String {
        let id = turnId ?? self.turnId
        let source = cardContextSource.map { #","card_context_source":"# + $0 } ?? ""
        return """
        {"id":"01TS","type":"turn_started","turn_id":"\(id.uuidString)","conversation_id":"\(conversationId.uuidString)"\(source)}
        """
    }

    private func turnCompletedJSON(turnId: UUID? = nil) -> String {
        let id = turnId ?? self.turnId
        return """
        {"id":"01TC","type":"turn_completed","turn_id":"\(id.uuidString)","terminal_state":"end_turn","total_cost_usd_micros":0,"iterations_count":1}
        """
    }

    private func blockStartTextJSON(blockId: String) -> String {
        """
        {"id":"01BS","type":"block_start","block":{"type":"text","block_id":"\(blockId)","text":""}}
        """
    }

    private func blockStartStatusJSON(blockId: String, label: String, state: String) -> String {
        """
        {"id":"01BS","type":"block_start","block":{"type":"status","block_id":"\(blockId)","label":"\(label)","state":"\(state)"}}
        """
    }

    private func blockStartConfirmationJSON(
        blockId: String, actionId: String, status: String
    ) -> String {
        """
        {"id":"01BS","type":"block_start","block":{"type":"confirmation","block_id":"\(blockId)","action_id":"\(actionId)","kind":"transfer","title":"Confirm deposit","rows":[{"label":"Amount","value":"$500.00"}],"details":{"operation":"deposit","direction":"INCOMING","amount":"500.00","currency":"USD","bank_institution":"Chase","bank_mask":"1234","bank_nickname":"Checking"},"confirm_label":"Confirm","cancel_label":"Cancel","hold_to_confirm":true,"status":"\(status)"}}
        """
    }

    private func emptyStockCardBlockStartJSON(blockId: String) -> String {
        """
        {"id":"01BS","type":"block_start","block":{"type":"stock_card","block_id":"\(blockId)","symbol":"AMD","company_name":"Advanced Micro Devices","logo_url":null,"price":0,"change_abs":0,"change_pct":0,"color_state":"neutral","bars":[],"range":"1D","range_options":["1D","1W","1M","3M","6M","1Y","ALL"]}}
        """
    }

    private func textDeltaJSON(blockId: String, text: String) -> String {
        let escaped = text.replacingOccurrences(of: "\"", with: "\\\"")
        return """
        {"id":"01TD","type":"text_delta","block_id":"\(blockId)","text":"\(escaped)"}
        """
    }

    private func blockDataJSON(blockId: String, patch: [String: Any]) -> String {
        let patchData = try! JSONSerialization.data(withJSONObject: patch)
        let patchString = String(data: patchData, encoding: .utf8)!
        return """
        {"id":"01BD","type":"block_data","block_id":"\(blockId)","data":\(patchString)}
        """
    }

    private func blockEndJSON(blockId: String) -> String {
        """
        {"id":"01BE","type":"block_end","block_id":"\(blockId)"}
        """
    }

    private func errorJSON(code: String, message: String?) -> String {
        let messageField = message.map { "\"\($0)\"" } ?? "null"
        return """
        {"id":"01ER","type":"error","code":"\(code)","message":\(messageField)}
        """
    }

    private func makeRaw(json: String) -> RawSSEEvent {
        RawSSEEvent(id: "01TEST", event: nil, data: json)
    }
}
