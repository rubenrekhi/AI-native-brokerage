import XCTest
@testable import Sevino

final class AssetSearchResultTests: XCTestCase {

    private var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    func testDecodesResultWithLogoUrl() throws {
        let json = """
        {
            "symbol": "TSLA",
            "name": "Tesla, Inc.",
            "logo_url": "https://financialmodelingprep.com/image-stock/TSLA.png"
        }
        """.data(using: .utf8)!

        let result = try decoder.decode(AssetSearchResult.self, from: json)

        XCTAssertEqual(result.symbol, "TSLA")
        XCTAssertEqual(result.name, "Tesla, Inc.")
        XCTAssertEqual(result.logoUrl, "https://financialmodelingprep.com/image-stock/TSLA.png")
    }

    func testDecodesResultWithNullLogoUrl() throws {
        let json = """
        {"symbol": "XYZ", "name": "Example Corp", "logo_url": null}
        """.data(using: .utf8)!

        let result = try decoder.decode(AssetSearchResult.self, from: json)

        XCTAssertEqual(result.symbol, "XYZ")
        XCTAssertEqual(result.name, "Example Corp")
        XCTAssertNil(result.logoUrl)
    }

    func testDecodesResultWithMissingLogoUrl() throws {
        let json = """
        {"symbol": "XYZ", "name": "Example Corp"}
        """.data(using: .utf8)!

        let result = try decoder.decode(AssetSearchResult.self, from: json)

        XCTAssertNil(result.logoUrl)
    }

    func testDecodesArrayResponse() throws {
        let json = """
        [
            {"symbol": "TSLA", "name": "Tesla, Inc.", "logo_url": "https://financialmodelingprep.com/image-stock/TSLA.png"},
            {"symbol": "TSM", "name": "Taiwan Semiconductor", "logo_url": null}
        ]
        """.data(using: .utf8)!

        let results = try decoder.decode([AssetSearchResult].self, from: json)

        XCTAssertEqual(results.count, 2)
        XCTAssertEqual(results[0].symbol, "TSLA")
        XCTAssertNil(results[1].logoUrl)
    }

    func testIdMatchesSymbol() {
        let result = AssetSearchResult(symbol: "AAPL", name: "Apple Inc.", logoUrl: nil)
        XCTAssertEqual(result.id, "AAPL")
    }
}
