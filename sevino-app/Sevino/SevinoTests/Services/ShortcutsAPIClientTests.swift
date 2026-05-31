import XCTest
@testable import Sevino

/// HTTP-level coverage for `ShortcutsAPIClient`. Verifies the path, the
/// envelope unwrap, and that all six backend category strings decode.
@MainActor
final class ShortcutsAPIClientTests: XCTestCase {

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

    func testFetchShortcutsHitsGetOnCorrectPath() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/shortcuts",
            response: .success(status: 200, body: Data(#"{"items":[]}"#.utf8))
        )

        let client = makeClient()
        _ = try await client.fetchShortcuts()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
        XCTAssertEqual(StubURLProtocol.lastRequest()?.url?.path, "/v1/shortcuts")
    }

    func testFetchShortcutsUnwrapsItemsEnvelope() async throws {
        let body = Data("""
        {
          "items": [
            {
              "id": "11111111-1111-1111-1111-111111111111",
              "text": "How's my portfolio?",
              "category": "first_time"
            },
            {
              "id": "22222222-2222-2222-2222-222222222222",
              "text": "Why is NVDA up?",
              "category": "portfolio_state"
            }
          ]
        }
        """.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/shortcuts",
            response: .success(status: 200, body: body)
        )

        let client = makeClient()
        let shortcuts = try await client.fetchShortcuts()

        XCTAssertEqual(shortcuts.count, 2)
        XCTAssertEqual(shortcuts[0].text, "How's my portfolio?")
        XCTAssertEqual(shortcuts[0].category, .firstTime)
        XCTAssertEqual(shortcuts[1].category, .portfolioState)
    }

    func testFetchShortcutsDecodesEveryCategory() async throws {
        // Lock in every backend category string. Any future rename on the
        // wire would silently route to a different Swift case (or crash);
        // this fails loudly instead.
        let body = Data("""
        {
          "items": [
            {"id": "11111111-1111-1111-1111-111111111111", "text": "a", "category": "first_time"},
            {"id": "22222222-2222-2222-2222-222222222222", "text": "b", "category": "portfolio_state"},
            {"id": "33333333-3333-3333-3333-333333333333", "text": "c", "category": "market_state"},
            {"id": "44444444-4444-4444-4444-444444444444", "text": "d", "category": "radar_update"},
            {"id": "55555555-5555-5555-5555-555555555555", "text": "e", "category": "capability"},
            {"id": "66666666-6666-6666-6666-666666666666", "text": "f", "category": "quiet_state"}
          ]
        }
        """.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/shortcuts",
            response: .success(status: 200, body: body)
        )

        let client = makeClient()
        let shortcuts = try await client.fetchShortcuts()

        XCTAssertEqual(shortcuts.map(\.category), [
            .firstTime, .portfolioState, .marketState,
            .radarUpdate, .capability, .quietState,
        ])
    }

    private func makeClient() -> ShortcutsAPIClient {
        let api = APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { nil }
        )
        return ShortcutsAPIClient(api: api)
    }
}
