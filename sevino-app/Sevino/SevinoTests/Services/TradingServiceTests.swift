import XCTest
@testable import Sevino

final class TradingServiceTests: XCTestCase {

    private var session: URLSession!

    override func setUp() {
        super.setUp()
        session = StubURLProtocol.makeSession()
    }

    override func tearDown() {
        StubURLProtocol.reset()
        session = nil
        super.tearDown()
    }

    // MARK: - listOrders

    func test_listOrders_buildsExpectedQueryString() async throws {
        let body = Data(#"{"orders":[]}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/orders",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        _ = try await service.listOrders(
            status: "closed",
            side: "buy",
            symbols: "AAPL,TSLA",
            after: Date(timeIntervalSince1970: 1_700_000_000),
            until: Date(timeIntervalSince1970: 1_710_000_000),
            limit: 50
        )

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        XCTAssertEqual(sent.httpMethod, "GET")
        let items = try XCTUnwrap(URLComponents(url: sent.url!, resolvingAgainstBaseURL: false)?.queryItems)
        let pairs = Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(pairs["limit"], "50")
        XCTAssertEqual(pairs["status"], "closed")
        XCTAssertEqual(pairs["side"], "buy")
        XCTAssertEqual(pairs["symbols"], "AAPL,TSLA")
        XCTAssertNotNil(pairs["after"])
        XCTAssertNotNil(pairs["until"])
    }

    func test_listOrders_omitsNilParameters() async throws {
        let body = Data(#"{"orders":[]}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/orders",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        _ = try await service.listOrders(
            status: nil,
            side: nil,
            symbols: nil,
            after: nil,
            until: nil,
            limit: 100
        )

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        let items = URLComponents(url: sent.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let names = Set(items.map(\.name))
        XCTAssertEqual(names, Set(["limit"]))
    }

    func test_listOrders_omitsEmptySymbols() async throws {
        let body = Data(#"{"orders":[]}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/orders",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        _ = try await service.listOrders(
            status: nil,
            side: nil,
            symbols: "",
            after: nil,
            until: nil,
            limit: 100
        )

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        let items = URLComponents(url: sent.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertNil(items.first(where: { $0.name == "symbols" }))
    }

    func test_listOrders_decodesOrderListResponse() async throws {
        let body = Data(#"""
        {
          "orders":[
            {
              "id":"ord_1",
              "client_order_id":"cli_1",
              "symbol":"AAPL",
              "asset_class":"us_equity",
              "side":"buy",
              "order_type":"market",
              "time_in_force":"day",
              "qty":"10",
              "notional":null,
              "filled_qty":"10",
              "filled_avg_price":"184.20",
              "limit_price":null,
              "stop_price":null,
              "status":"filled",
              "submitted_at":"2026-04-22T15:30:00Z",
              "filled_at":"2026-04-22T15:30:01Z",
              "canceled_at":null,
              "expired_at":null,
              "failed_at":null,
              "created_at":"2026-04-22T15:30:00Z"
            }
          ]
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/orders",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let orders = try await service.listOrders(
            status: nil, side: nil, symbols: nil,
            after: nil, until: nil, limit: 100
        )

        XCTAssertEqual(orders.count, 1)
        XCTAssertEqual(orders[0].id, "ord_1")
        XCTAssertEqual(orders[0].symbol, "AAPL")
        XCTAssertEqual(orders[0].sideKind, .buy)
        XCTAssertEqual(orders[0].statusKind, .completed)
    }

    func test_listOrders_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Forbidden","code":"FORBIDDEN"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/orders",
            response: .success(status: 403, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.listOrders(
                status: nil, side: nil, symbols: nil,
                after: nil, until: nil, limit: 100
            )
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "FORBIDDEN")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - placeOrder

    func test_placeOrder_postsToOrdersEndpointWithBody() async throws {
        let body = Data(#"""
        {
          "id": "ord_1",
          "alpaca_order_id": "alp_1",
          "symbol": "AAPL",
          "side": "buy",
          "type": "market",
          "time_in_force": "day",
          "qty": "5",
          "notional": null,
          "limit_price": null,
          "status": "accepted",
          "submitted_at": null,
          "created_at": "2026-04-28T10:00:00Z"
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/trading/orders",
            response: .success(status: 201, body: body)
        )

        let service = makeService()
        let response = try await service.placeOrder(
            PlaceOrderRequest(
                symbol: "AAPL",
                side: "buy",
                type: "market",
                qty: "5",
                notional: nil,
                limitPrice: nil,
                conversationId: "conv_1"
            )
        )

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        XCTAssertEqual(sent.httpMethod, "POST")
        XCTAssertEqual(sent.url?.path, "/v1/trading/orders")

        // URLSession moves request bodies to httpBodyStream when running through
        // the protocol stub, so read the stream rather than httpBody.
        let sentBody = try XCTUnwrap(Self.bodyData(from: sent))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: sentBody) as? [String: Any])
        XCTAssertEqual(json["symbol"] as? String, "AAPL")
        XCTAssertEqual(json["side"] as? String, "buy")
        XCTAssertEqual(json["type"] as? String, "market")
        XCTAssertEqual(json["qty"] as? String, "5")
        XCTAssertEqual(json["conversation_id"] as? String, "conv_1")

        XCTAssertEqual(response.id, "ord_1")
        XCTAssertEqual(response.alpacaOrderId, "alp_1")
        XCTAssertEqual(response.timeInForce, "day")
    }

    func test_placeOrder_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Account not active","code":"ACCOUNT_NOT_ACTIVE"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/trading/orders",
            response: .success(status: 409, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.placeOrder(
                PlaceOrderRequest(
                    symbol: "AAPL", side: "buy", type: "market",
                    qty: "1", notional: nil, limitPrice: nil, conversationId: nil
                )
            )
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "ACCOUNT_NOT_ACTIVE")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - cancelOrder

    func test_cancelOrder_sendsDeleteToOrdersIdEndpoint() async throws {
        let body = Data(#"""
        {
          "id": "ord_2",
          "alpaca_order_id": "alp_2",
          "symbol": "TSLA",
          "side": "sell",
          "type": "market",
          "time_in_force": "day",
          "qty": "1",
          "notional": null,
          "limit_price": null,
          "status": "pending_cancel",
          "submitted_at": "2026-04-28T10:00:00Z",
          "created_at": "2026-04-28T10:00:00Z",
          "filled_qty": null,
          "filled_avg_price": null,
          "filled_at": null,
          "conversation_id": null
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/trading/orders/ord_2",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let response = try await service.cancelOrder(id: "ord_2")

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        XCTAssertEqual(sent.httpMethod, "DELETE")
        XCTAssertEqual(sent.url?.path, "/v1/trading/orders/ord_2")
        XCTAssertEqual(response.id, "ord_2")
        XCTAssertEqual(response.status, "pending_cancel")
    }

    // MARK: - getOrder

    func test_getOrder_fetchesOrdersIdEndpoint() async throws {
        let body = Data(#"""
        {
          "id": "ord_3",
          "alpaca_order_id": "alp_3",
          "symbol": "MSFT",
          "side": "buy",
          "type": "limit",
          "time_in_force": "gtc",
          "qty": "2",
          "notional": null,
          "limit_price": "300.00",
          "status": "filled",
          "submitted_at": "2026-04-28T10:00:00Z",
          "created_at": "2026-04-28T10:00:00Z",
          "filled_qty": "2",
          "filled_avg_price": "299.85",
          "filled_at": "2026-04-28T10:00:05Z",
          "conversation_id": null
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/trading/orders/ord_3",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let response = try await service.getOrder(id: "ord_3")

        let sent = try XCTUnwrap(StubURLProtocol.lastRequest())
        XCTAssertEqual(sent.httpMethod, "GET")
        XCTAssertEqual(sent.url?.path, "/v1/trading/orders/ord_3")
        XCTAssertEqual(response.filledQty, "2")
        XCTAssertEqual(response.filledAvgPrice, "299.85")
    }

    // MARK: - listPositions

    func test_listPositions_hitsExpectedPath() async throws {
        let body = Data(#"""
        {"positions":[{"symbol":"AAPL","asset_class":"us_equity","qty":"10","market_value":"1842.00"}]}
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/positions",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let positions = try await service.listPositions()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
        XCTAssertEqual(StubURLProtocol.lastRequest()?.url?.path, "/v1/brokerage/positions")
        XCTAssertEqual(positions.count, 1)
        XCTAssertEqual(positions[0].symbol, "AAPL")
    }

    // MARK: - Helpers

    private func makeService() -> TradingService {
        let client = APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { nil }
        )
        return TradingService(api: client)
    }

    /// URLSession converts request bodies to `httpBodyStream` when sent through
    /// a custom URLProtocol, so `httpBody` is nil at the recorded-request layer.
    /// This drains the stream to bytes for body assertions.
    private static func bodyData(from request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var buffer = [UInt8](repeating: 0, count: 4096)
        var data = Data()
        while stream.hasBytesAvailable {
            let read = stream.read(&buffer, maxLength: buffer.count)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }
}
