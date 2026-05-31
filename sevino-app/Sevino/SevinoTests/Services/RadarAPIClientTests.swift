import XCTest
@testable import Sevino

/// Exercises the actual HTTP plumbing (path, method, body shape, status-code
/// handling) of `RadarAPIClient`. The view-model-level tests use a mock
/// client which can't catch a typo in the URL path — this file does.
@MainActor
final class RadarAPIClientTests: XCTestCase {

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

    // MARK: - fetchRadar

    func testFetchRadarHitsGetOnCorrectPath() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar",
            response: .success(status: 200, body: Self.emptyListBody)
        )

        let client = makeClient()
        _ = try await client.fetchRadar()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
        XCTAssertEqual(StubURLProtocol.lastRequest()?.url?.path, "/v1/radar")
    }

    func testFetchRadarDecodesItemsAndAnchor() async throws {
        let body = Data("""
        {
          "items": [
            {
              "id": "11111111-1111-1111-1111-111111111111",
              "symbol": "NVDA",
              "company_name": "Nvidia",
              "context_blurb": "Top AI chip name",
              "source": "ai_generated",
              "bucket": "broad_notable",
              "is_favorited": false,
              "relevance_score": 0.9,
              "expires_at": "2026-06-10T00:00:00Z",
              "created_at": "2026-06-03T00:00:00Z",
              "price": "100.00",
              "change_abs": "1.24",
              "change_pct": "0.0124"
            }
          ],
          "next_refresh_at": "2026-06-10T13:00:00Z"
        }
        """.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar",
            response: .success(status: 200, body: body)
        )

        let client = makeClient()
        let response = try await client.fetchRadar()

        XCTAssertEqual(response.items.count, 1)
        XCTAssertEqual(response.items[0].ticker, "NVDA")
        XCTAssertEqual(response.items[0].source, .aiGenerated)
        XCTAssertEqual(response.items[0].bucket, "broad_notable")
        XCTAssertNotNil(response.nextRefreshAt)
    }

    // MARK: - toggleFavorite

    func testToggleFavoriteSendsPatchWithSnakeCaseBody() async throws {
        let itemID = UUID()
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar/\(itemID.uuidString)",
            response: .success(status: 200, body: Self.singleItemBody(id: itemID, isFavorited: true))
        )

        let client = makeClient()
        _ = try await client.toggleFavorite(itemId: itemID, isFavorited: true)

        let sent = StubURLProtocol.lastRequest()
        XCTAssertEqual(sent?.httpMethod, "PATCH")
        XCTAssertEqual(sent?.url?.path, "/v1/radar/\(itemID.uuidString)")

        let sentBody = sent?.httpBodyStream.flatMap { readAll($0) } ?? Data()
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: sentBody) as? [String: Any])
        XCTAssertEqual(json["is_favorited"] as? Bool, true,
                       "body must use snake_case to match backend wire contract")
    }

    func testToggleFavorite204ReturnsNil() async throws {
        let itemID = UUID()
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar/\(itemID.uuidString)",
            response: .success(status: 204, body: Data())
        )

        let client = makeClient()
        let result = try await client.toggleFavorite(itemId: itemID, isFavorited: false)

        XCTAssertNil(result, "204 indicates the server deleted a user_added row")
    }

    // MARK: - deleteRadarItem

    func testDeleteRadarItemHitsDeleteOnCorrectPath() async throws {
        let itemID = UUID()
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar/\(itemID.uuidString)",
            response: .success(status: 204, body: Data())
        )

        let client = makeClient()
        try await client.deleteRadarItem(itemId: itemID)

        let sent = StubURLProtocol.lastRequest()
        XCTAssertEqual(sent?.httpMethod, "DELETE")
        XCTAssertEqual(sent?.url?.path, "/v1/radar/\(itemID.uuidString)")
    }

    // MARK: - addRadarItem

    func testAddRadarItemPostsSymbolBody() async throws {
        let itemID = UUID()
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/radar",
            response: .success(status: 200, body: Self.singleItemBody(id: itemID, isFavorited: true))
        )

        let client = makeClient()
        _ = try await client.addRadarItem(symbol: "TSLA")

        let sent = StubURLProtocol.lastRequest()
        XCTAssertEqual(sent?.httpMethod, "POST")
        XCTAssertEqual(sent?.url?.path, "/v1/radar")

        let sentBody = sent?.httpBodyStream.flatMap { readAll($0) } ?? Data()
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: sentBody) as? [String: Any])
        XCTAssertEqual(json["symbol"] as? String, "TSLA")
    }

    // MARK: - Helpers

    private func makeClient() -> RadarAPIClient {
        let api = APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { nil }
        )
        return RadarAPIClient(api: api)
    }

    private func readAll(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: 1024)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }

    private static let emptyListBody = Data(#"{"items":[],"next_refresh_at":null}"#.utf8)

    private static func singleItemBody(id: UUID, isFavorited: Bool) -> Data {
        Data("""
        {
          "id": "\(id.uuidString)",
          "symbol": "AAPL",
          "company_name": "Apple",
          "context_blurb": "Iconic device maker",
          "source": "ai_generated",
          "bucket": "broad_notable",
          "is_favorited": \(isFavorited),
          "relevance_score": 0.8,
          "expires_at": null,
          "created_at": "2026-06-03T00:00:00Z",
          "price": null,
          "change_abs": null,
          "change_pct": null
        }
        """.utf8)
    }
}
