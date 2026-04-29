import XCTest
@testable import Sevino

final class SingleStockCardDataTests: XCTestCase {

    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    private var canonicalStatsJSON: String {
        """
        {
            "bid": "123.25",
            "ask": "432.52",
            "lastSale": "234.25",
            "open": "234.25",
            "high": "642.54",
            "low": "248.14",
            "exchange": "NASDAQ",
            "marketCap": "12B",
            "peRatio": "23.31",
            "fiftyTwoWeekHigh": "234.24",
            "fiftyTwoWeekLow": "125.36",
            "volume": "341.24K",
            "avgVolume": "75.35K",
            "marginReq": "20.00%"
        }
        """
    }

    private func canonicalCardJSON(withStats: Bool) -> String {
        let statsField = withStats ? ",\n            \"stats\": \(canonicalStatsJSON)" : ""
        return """
        {
            "ticker": "AMD",
            "companyName": "Advanced Micro Devices Inc.",
            "price": "$184.92",
            "gainLossText": "$2.12 (0.53%)",
            "isPositive": true,
            "periodLabel": "Past 30 Days",
            "chartPoints": [0.1, 0.25, 0.4, 0.7],
            "selectedTimeRange": "1M"\(statsField)
        }
        """
    }

    func testDecodesExpandedPayloadPopulatesAllFields() throws {
        let json = canonicalCardJSON(withStats: true).data(using: .utf8)!

        let data = try decoder.decode(SingleStockCardData.self, from: json)

        XCTAssertEqual(data.ticker, "AMD")
        XCTAssertEqual(data.companyName, "Advanced Micro Devices Inc.")
        XCTAssertEqual(data.price, "$184.92")
        XCTAssertEqual(data.gainLossText, "$2.12 (0.53%)")
        XCTAssertTrue(data.isPositive)
        XCTAssertEqual(data.periodLabel, "Past 30 Days")
        XCTAssertEqual(data.chartPoints, [0.1, 0.25, 0.4, 0.7])
        XCTAssertEqual(data.selectedTimeRange, .oneMonth)

        let stats = try XCTUnwrap(data.stats)
        XCTAssertEqual(stats.bid, "123.25")
        XCTAssertEqual(stats.ask, "432.52")
        XCTAssertEqual(stats.lastSale, "234.25")
        XCTAssertEqual(stats.open, "234.25")
        XCTAssertEqual(stats.high, "642.54")
        XCTAssertEqual(stats.low, "248.14")
        XCTAssertEqual(stats.exchange, "NASDAQ")
        XCTAssertEqual(stats.marketCap, "12B")
        XCTAssertEqual(stats.peRatio, "23.31")
        XCTAssertEqual(stats.fiftyTwoWeekHigh, "234.24")
        XCTAssertEqual(stats.fiftyTwoWeekLow, "125.36")
        XCTAssertEqual(stats.volume, "341.24K")
        XCTAssertEqual(stats.avgVolume, "75.35K")
        XCTAssertEqual(stats.marginReq, "20.00%")
    }

    func testDecodesCompactPayloadWithoutStats() throws {
        let json = canonicalCardJSON(withStats: false).data(using: .utf8)!

        let data = try decoder.decode(SingleStockCardData.self, from: json)

        XCTAssertNil(data.stats)
        XCTAssertEqual(data.ticker, "AMD")
    }

    func testRoundTripPreservesShape() throws {
        let original = SingleStockCardData(
            ticker: "NVDA",
            companyName: "NVIDIA Corp.",
            price: "$875.30",
            gainLossText: "+$12.40 (1.43%)",
            isPositive: true,
            periodLabel: "Today",
            chartPoints: [0.2, 0.4, 0.6],
            selectedTimeRange: .oneWeek,
            stats: nil
        )

        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(SingleStockCardData.self, from: encoded)

        XCTAssertEqual(decoded, original)
    }

    func testEquatableDistinguishesTimeRangeChange() {
        let base = SingleStockCardData(
            ticker: "AMD",
            companyName: "Advanced Micro Devices Inc.",
            price: "$184.92",
            gainLossText: "$2.12 (0.53%)",
            isPositive: true,
            periodLabel: "Past 30 Days",
            chartPoints: [0.1, 0.2],
            selectedTimeRange: .oneMonth,
            stats: nil
        )

        let other = SingleStockCardData(
            ticker: base.ticker,
            companyName: base.companyName,
            price: base.price,
            gainLossText: base.gainLossText,
            isPositive: base.isPositive,
            periodLabel: base.periodLabel,
            chartPoints: base.chartPoints,
            selectedTimeRange: .oneWeek,
            stats: nil
        )

        XCTAssertNotEqual(base, other)
    }

    func testDecodingFailsWhenRequiredKeyMissing() {
        let json = """
        {
            "ticker": "AMD",
            "companyName": "Advanced Micro Devices Inc.",
            "price": "$184.92",
            "gainLossText": "$2.12 (0.53%)",
            "isPositive": true,
            "periodLabel": "Past 30 Days",
            "chartPoints": [0.1, 0.2]
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try decoder.decode(SingleStockCardData.self, from: json))
    }
}
