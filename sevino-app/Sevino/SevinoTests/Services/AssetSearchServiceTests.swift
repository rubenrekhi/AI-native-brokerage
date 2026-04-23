import XCTest
@testable import Sevino

final class AssetSearchServiceTests: XCTestCase {

    private var mockAPI: MockAPIClient!
    private var service: AssetSearchService!

    override func setUp() {
        mockAPI = MockAPIClient()
        service = AssetSearchService(api: mockAPI)
    }

    func testSearchHitsExpectedPath() async throws {
        mockAPI.responseToReturn = [AssetSearchResult]()

        _ = try await service.search(query: "TS", limit: 10)

        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertEqual(mockAPI.lastPath, "/v1/assets/search?q=TS&limit=10")
    }

    func testSearchUsesDefaultLimit() async throws {
        mockAPI.responseToReturn = [AssetSearchResult]()

        _ = try await service.search(query: "T")

        XCTAssertEqual(mockAPI.lastPath, "/v1/assets/search?q=T&limit=10")
    }

    func testSearchPercentEncodesQuery() async throws {
        mockAPI.responseToReturn = [AssetSearchResult]()

        _ = try await service.search(query: "A B", limit: 5)

        // URLComponents encodes the space as `%20` in query items.
        XCTAssertEqual(mockAPI.lastPath, "/v1/assets/search?q=A%20B&limit=5")
    }

    func testSearchReturnsDecodedResults() async throws {
        mockAPI.responseToReturn = [
            AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: "https://example.com/TSLA.png"),
            AssetSearchResult(symbol: "TSM", name: "Taiwan Semiconductor", logoUrl: nil),
        ]

        let results = try await service.search(query: "TS", limit: 10)

        XCTAssertEqual(results.count, 2)
        XCTAssertEqual(results[0].symbol, "TSLA")
        XCTAssertEqual(results[1].logoUrl, nil)
    }

    func testSearchPropagatesErrors() async {
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)

        do {
            _ = try await service.search(query: "TS", limit: 10)
            XCTFail("Expected error")
        } catch {
            XCTAssertTrue(error is URLError)
        }
    }
}
