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
}
