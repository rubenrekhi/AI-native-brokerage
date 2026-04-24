import XCTest
@testable import Sevino

final class RadarCardDataTests: XCTestCase {

    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    private var canonicalItemJSON: String {
        """
        {
            "ticker": "AAPL",
            "description": "Apple earnings beat expectations",
            "price": "$189.42",
            "changePercent": "+1.24%",
            "isPositive": true,
            "expiresIn": "2h",
            "isStarred": true
        }
        """
    }

    func testRadarCardDataDecodesFromCanonicalJSON() throws {
        let json = """
        {
            "items": [
                \(canonicalItemJSON),
                {
                    "ticker": "TSLA",
                    "description": "Tesla deliveries miss guidance",
                    "price": "$242.10",
                    "changePercent": "-3.10%",
                    "isPositive": false,
                    "expiresIn": "45m",
                    "isStarred": false
                }
            ]
        }
        """.data(using: .utf8)!

        let data = try decoder.decode(RadarCardData.self, from: json)

        XCTAssertEqual(data.items.count, 2)
        XCTAssertEqual(data.items[0].ticker, "AAPL")
        XCTAssertEqual(data.items[1].ticker, "TSLA")
    }

    func testRadarCardDataDecodesEmptyItems() throws {
        let json = #"{"items": []}"#.data(using: .utf8)!

        let data = try decoder.decode(RadarCardData.self, from: json)

        XCTAssertTrue(data.items.isEmpty)
    }

    func testRadarItemDecodesAllRequiredFields() throws {
        let json = canonicalItemJSON.data(using: .utf8)!

        let item = try decoder.decode(RadarItem.self, from: json)

        XCTAssertEqual(item.ticker, "AAPL")
        XCTAssertEqual(item.description, "Apple earnings beat expectations")
        XCTAssertEqual(item.price, "$189.42")
        XCTAssertEqual(item.changePercent, "+1.24%")
        XCTAssertTrue(item.isPositive)
        XCTAssertEqual(item.expiresIn, "2h")
        XCTAssertTrue(item.isStarred)
    }

    func testRadarItemIdMatchesTicker() throws {
        let json = canonicalItemJSON.data(using: .utf8)!

        let item = try decoder.decode(RadarItem.self, from: json)

        XCTAssertEqual(item.id, "AAPL")
    }

    func testRadarCardDataRoundTripPreservesShape() throws {
        let original = RadarCardData(items: [
            RadarItem(
                ticker: "NVDA",
                description: "NVIDIA Q4 beat",
                price: "$875.30",
                changePercent: "+4.12%",
                isPositive: true,
                expiresIn: "1h",
                isStarred: false
            )
        ])

        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(RadarCardData.self, from: encoded)

        XCTAssertEqual(decoded.items.count, 1)
        let item = decoded.items[0]
        XCTAssertEqual(item.ticker, "NVDA")
        XCTAssertEqual(item.description, "NVIDIA Q4 beat")
        XCTAssertEqual(item.price, "$875.30")
        XCTAssertEqual(item.changePercent, "+4.12%")
        XCTAssertTrue(item.isPositive)
        XCTAssertEqual(item.expiresIn, "1h")
        XCTAssertFalse(item.isStarred)
    }

    func testRadarItemDecodingFailsWhenRequiredKeyMissing() {
        let json = """
        {
            "ticker": "AAPL",
            "description": "Apple earnings beat expectations",
            "price": "$189.42",
            "changePercent": "+1.24%",
            "isPositive": true,
            "expiresIn": "2h"
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try decoder.decode(RadarItem.self, from: json))
    }
}
