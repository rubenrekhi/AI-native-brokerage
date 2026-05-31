import XCTest
@testable import Sevino

final class SSEEventTests: XCTestCase {

    private let decoder = JSONDecoder()

    // MARK: - Per-variant decoding (acceptance: round-trip wire JSON)

    func testDecodesTurnStarted() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000001",
            "type": "turn_started",
            "turn_id": "11111111-2222-3333-4444-555555555555",
            "conversation_id": "66666666-7777-8888-9999-AAAAAAAAAAAA",
            "card_context_source": {"symbol": "AAPL", "kind": "earnings_result"}
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .turnStarted(payload) = event else {
            XCTFail("expected .turnStarted, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000001")
        XCTAssertEqual(payload.turnId, UUID(uuidString: "11111111-2222-3333-4444-555555555555"))
        XCTAssertEqual(payload.conversationId, UUID(uuidString: "66666666-7777-8888-9999-AAAAAAAAAAAA"))
        XCTAssertEqual(payload.cardContextSource, CardContextSource(symbol: "AAPL", kind: "earnings_result"))
        XCTAssertEqual(event.wireType, "turn_started")
    }

    func testDecodesTurnStartedWithoutCardContextSource() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000001",
            "type": "turn_started",
            "turn_id": "11111111-2222-3333-4444-555555555555",
            "conversation_id": "66666666-7777-8888-9999-AAAAAAAAAAAA"
        }
        """.utf8)

        guard case let .turnStarted(payload) = try SSEEvent.decode(from: json) else {
            return XCTFail("expected .turnStarted")
        }
        XCTAssertNil(payload.cardContextSource)
    }

    func testDecodesStatus() throws {
        let json = Data("""
        {"id": "01HX0000000000000000000002", "type": "status", "label": "thinking…"}
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .status(payload) = event else {
            XCTFail("expected .status, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000002")
        XCTAssertEqual(payload.label, "thinking…")
    }

    func testDecodesBlockStartWithOpaqueBlockPayload() throws {
        // The `block` field's schema is owned by the C3.3 `Block` enum;
        // SSEEvent preserves it as-is so a later layer can interpret it.
        let json = Data("""
        {
            "id": "01HX0000000000000000000003",
            "type": "block_start",
            "block": {"type": "text", "block_id": "b1", "text": ""}
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .blockStart(payload) = event else {
            XCTFail("expected .blockStart, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000003")
        XCTAssertEqual(payload.block, .object([
            "type": .string("text"),
            "block_id": .string("b1"),
            "text": .string(""),
        ]))
    }

    func testDecodesTextDelta() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000004",
            "type": "text_delta",
            "block_id": "b1",
            "text": "hello "
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .textDelta(payload) = event else {
            XCTFail("expected .textDelta, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000004")
        XCTAssertEqual(payload.blockId, "b1")
        XCTAssertEqual(payload.text, "hello ")
    }

    func testDecodesBlockData() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000005",
            "type": "block_data",
            "block_id": "b2",
            "data": {"price": 123.45, "bars": [1, 2, 3]}
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .blockData(payload) = event else {
            XCTFail("expected .blockData, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000005")
        XCTAssertEqual(payload.blockId, "b2")
        XCTAssertEqual(payload.data, .object([
            "price": .double(123.45),
            "bars": .array([.int(1), .int(2), .int(3)]),
        ]))
    }

    func testDecodesBlockEnd() throws {
        let json = Data("""
        {"id": "01HX0000000000000000000006", "type": "block_end", "block_id": "b1"}
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .blockEnd(payload) = event else {
            XCTFail("expected .blockEnd, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000006")
        XCTAssertEqual(payload.blockId, "b1")
    }

    func testDecodesTurnCompleted() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000007",
            "type": "turn_completed",
            "turn_id": "11111111-2222-3333-4444-555555555555",
            "terminal_state": "ok",
            "total_cost_usd_micros": 12345,
            "iterations_count": 1
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .turnCompleted(payload) = event else {
            XCTFail("expected .turnCompleted, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000007")
        XCTAssertEqual(payload.turnId, UUID(uuidString: "11111111-2222-3333-4444-555555555555"))
        XCTAssertEqual(payload.terminalState, "ok")
        XCTAssertEqual(payload.totalCostUsdMicros, 12345)
        XCTAssertEqual(payload.iterationsCount, 1)
    }

    func testDecodesErrorWithMessage() throws {
        let json = Data("""
        {
            "id": "01HX0000000000000000000008",
            "type": "error",
            "code": "model_rate_limit",
            "message": "429 from upstream"
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .error(payload) = event else {
            XCTFail("expected .error, got \(event)")
            return
        }
        XCTAssertEqual(payload.id, "01HX0000000000000000000008")
        XCTAssertEqual(payload.code, .modelRateLimit)
        XCTAssertEqual(payload.message, "429 from upstream")
    }

    func testDecodesErrorWithoutMessage() throws {
        // The backend ships `"message": null` for errors with no upstream
        // exception (e.g. cap-breach). Optional decoding should accept that.
        let json = Data("""
        {
            "id": "01HX0000000000000000000009",
            "type": "error",
            "code": "cancelled",
            "message": null
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .error(payload) = event else {
            XCTFail("expected .error, got \(event)")
            return
        }
        XCTAssertEqual(payload.code, .cancelled)
        XCTAssertNil(payload.message)
    }

    // MARK: - ErrorCode taxonomy

    func testEveryErrorCodeFromBackendDecodes() throws {
        // Locks the closed taxonomy from `app/ai/runtime/errors.py:ErrorCode`.
        // If a new code lands on the backend, this test fails until the iOS
        // enum is updated — exactly the loud-failure behaviour we want.
        let codes: [(wire: String, expected: SSEEvent.ErrorCode)] = [
            ("tool_timeout", .toolTimeout),
            ("tool_error", .toolError),
            ("model_overloaded", .modelOverloaded),
            ("model_rate_limit", .modelRateLimit),
            ("internal_error", .internalError),
            ("cancelled", .cancelled),
            ("turn_iteration_limit", .turnIterationLimit),
            ("tool_call_limit", .toolCallLimit),
            ("output_token_limit", .outputTokenLimit),
            ("validation_error", .validationError),
        ]
        for (wire, expected) in codes {
            let json = Data("""
            {"id": "01", "type": "error", "code": "\(wire)"}
            """.utf8)
            let event = try SSEEvent.decode(from: json)
            guard case let .error(payload) = event else {
                XCTFail("expected .error for code \(wire)")
                continue
            }
            XCTAssertEqual(payload.code, expected, "wire code \(wire) mapped wrong")
        }
    }

    func testUnknownErrorCodeDegradesToUnknown() throws {
        // Backend taxonomy is closed, but a future code shipping ahead of the
        // iOS update should NOT fail decoding the whole frame — the human
        // `message` is still useful for surfacing.
        let json = Data("""
        {
            "id": "01",
            "type": "error",
            "code": "future_code_we_havent_seen",
            "message": "something went wrong"
        }
        """.utf8)

        let event = try SSEEvent.decode(from: json)

        guard case let .error(payload) = event else {
            XCTFail("expected .error, got \(event)")
            return
        }
        XCTAssertEqual(payload.code, .unknown)
        XCTAssertEqual(payload.message, "something went wrong")
    }

    // MARK: - Discriminator failure modes

    func testUnknownEventTypeThrowsClearError() {
        // Unknown discriminators must surface loudly — silently dropping
        // would hide schema drift between backend and iOS.
        let json = Data("""
        {"id": "01", "type": "not_a_real_event"}
        """.utf8)

        do {
            _ = try SSEEvent.decode(from: json)
            XCTFail("expected decode to throw on unknown event type")
        } catch let DecodingError.dataCorrupted(context) {
            XCTAssertTrue(
                context.debugDescription.contains("not_a_real_event"),
                "error message should name the unknown type, got: \(context.debugDescription)"
            )
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testMissingDiscriminatorThrows() {
        let json = Data("""
        {"id": "01", "label": "no type field"}
        """.utf8)

        XCTAssertThrowsError(try SSEEvent.decode(from: json))
    }

    func testMissingRequiredFieldForVariantThrows() {
        // text_delta requires both `block_id` and `text`. The variant payload
        // decoder should surface the missing field rather than silently
        // dropping the event.
        let json = Data("""
        {"id": "01", "type": "text_delta", "block_id": "b1"}
        """.utf8)

        XCTAssertThrowsError(try SSEEvent.decode(from: json)) { error in
            guard case let DecodingError.keyNotFound(key, _) = error else {
                XCTFail("expected .keyNotFound, got \(error)")
                return
            }
            XCTAssertEqual(key.stringValue, "text")
        }
    }

    func testWrongTypeForFieldThrows() {
        // turn_id must be a UUID string. A number should fail decoding rather
        // than silently coerce.
        let json = Data("""
        {
            "id": "01",
            "type": "turn_started",
            "turn_id": 12345,
            "conversation_id": "66666666-7777-8888-9999-AAAAAAAAAAAA"
        }
        """.utf8)

        XCTAssertThrowsError(try SSEEvent.decode(from: json))
    }

    func testMalformedJSONThrows() {
        // The convenience decoder must surface JSONDecoder's own errors
        // (not just our discriminator errors) and — in DEBUG — log them.
        let json = Data("not even json".utf8)

        XCTAssertThrowsError(try SSEEvent.decode(from: json))
    }

    // MARK: - Round-trip via standard JSONDecoder

    func testInitFromDecoderUsesTypeDiscriminator() throws {
        // Pins the contract that the `init(from:)` reads the JSON-level `type`
        // field — independent of the convenience `decode(from:)` helper, so a
        // future caller using `JSONDecoder().decode(SSEEvent.self, ...)`
        // directly still routes correctly.
        let json = Data("""
        {"id": "01", "type": "status", "label": "x"}
        """.utf8)

        let event = try JSONDecoder().decode(SSEEvent.self, from: json)

        if case .status = event {
            // ok
        } else {
            XCTFail("expected .status from direct decoder, got \(event)")
        }
    }
}
