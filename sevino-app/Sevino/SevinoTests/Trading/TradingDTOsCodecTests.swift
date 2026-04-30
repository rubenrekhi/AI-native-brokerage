import XCTest
@testable import Sevino

/// Locks the wire contract for the trade-execution DTOs. The backend speaks
/// snake_case and `APIClient` configures `convertToSnakeCase` / `convertFromSnakeCase`
/// — these tests make the camelCase ↔ snake_case mapping a regression target
/// so a rename or a case-conversion regression breaks here, not at runtime.
final class TradingDTOsCodecTests: XCTestCase {

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func test_placeOrderRequest_encodesSnakeCaseKeys() throws {
        let request = PlaceOrderRequest(
            symbol: "AAPL",
            side: "buy",
            type: "limit",
            qty: "5",
            notional: nil,
            limitPrice: "199.50",
            conversationId: "conv_1"
        )

        let data = try encoder.encode(request)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertEqual(json["symbol"] as? String, "AAPL")
        XCTAssertEqual(json["limit_price"] as? String, "199.50")
        XCTAssertEqual(json["conversation_id"] as? String, "conv_1")
        XCTAssertNil(json["limitPrice"])
        XCTAssertNil(json["conversationId"])
    }

    func test_placeOrderResponse_decodesSnakeCaseKeys() throws {
        let payload = """
        {
            "id": "ord_1",
            "alpaca_order_id": "alp_1",
            "symbol": "AAPL",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": null,
            "notional": "100.00",
            "limit_price": null,
            "status": "accepted",
            "submitted_at": null,
            "created_at": "2026-04-28T10:00:00Z"
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(PlaceOrderResponse.self, from: payload)

        XCTAssertEqual(response.id, "ord_1")
        XCTAssertEqual(response.alpacaOrderId, "alp_1")
        XCTAssertEqual(response.timeInForce, "day")
        XCTAssertEqual(response.notional, "100.00")
        XCTAssertEqual(response.createdAt, "2026-04-28T10:00:00Z")
    }

    func test_orderDetailResponse_decodesFillAndConversationFields() throws {
        let payload = """
        {
            "id": "ord_2",
            "alpaca_order_id": "alp_2",
            "symbol": "TSLA",
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "qty": "5",
            "notional": null,
            "limit_price": null,
            "status": "filled",
            "submitted_at": "2026-04-28T10:00:00Z",
            "created_at": "2026-04-28T10:00:00Z",
            "filled_qty": "5",
            "filled_avg_price": "200.10",
            "filled_at": "2026-04-28T10:00:01Z",
            "conversation_id": "conv_99"
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(OrderDetailResponse.self, from: payload)

        XCTAssertEqual(response.filledQty, "5")
        XCTAssertEqual(response.filledAvgPrice, "200.10")
        XCTAssertEqual(response.filledAt, "2026-04-28T10:00:01Z")
        XCTAssertEqual(response.conversationId, "conv_99")
    }

    /// Debug-surface and other non-chat-driven orders return `conversation_id: null`.
    /// Lock the `Optional` round-trip so a regression that drops the optional
    /// (or stops emitting the key entirely) breaks here, not at runtime.
    func test_orderDetailResponse_decodesWithNullConversationId() throws {
        let payload = """
        {
            "id": "ord_3",
            "alpaca_order_id": "alp_3",
            "symbol": "AAPL",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": null,
            "notional": "100.00",
            "limit_price": null,
            "status": "accepted",
            "submitted_at": null,
            "created_at": "2026-04-28T10:00:00Z",
            "filled_qty": null,
            "filled_avg_price": null,
            "filled_at": null,
            "conversation_id": null
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(OrderDetailResponse.self, from: payload)

        XCTAssertNil(response.conversationId)
        XCTAssertNil(response.qty)
        XCTAssertEqual(response.notional, "100.00")
        XCTAssertNil(response.filledQty)
        XCTAssertNil(response.filledAvgPrice)
        XCTAssertNil(response.filledAt)
        XCTAssertNil(response.submittedAt)
    }
}
