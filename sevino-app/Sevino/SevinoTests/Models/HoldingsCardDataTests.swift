import XCTest
@testable import Sevino

final class HoldingsCardDataTests: XCTestCase {

    private let sampleHoldings: [Holding] = [
        Holding(
            ticker: "AAPL",
            isCash: false,
            shares: "10",
            value: "$1,820.50",
            gainLossText: "+$120.50 (7.08%)",
            isPositive: true,
            daysGain: "+$12.30",
            daysGainPercent: "0.68%",
            totalGain: "+$120.50",
            totalGainPercent: "7.08%",
            averageCost: "$170.00"
        ),
        Holding(
            ticker: "Cash",
            isCash: true,
            shares: nil,
            value: "$250.00",
            gainLossText: nil,
            isPositive: nil,
            daysGain: nil,
            daysGainPercent: nil,
            totalGain: nil,
            totalGainPercent: nil,
            averageCost: nil
        )
    ]

    func testHoldingsCardDataEncodesAndDecodesRoundTrip() throws {
        let original = HoldingsCardData(holdings: sampleHoldings, displayOption: "Total Value")

        let encoded = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(HoldingsCardData.self, from: encoded)

        XCTAssertEqual(decoded.displayOption, "Total Value")
        XCTAssertEqual(decoded.holdings.count, 2)

        let aapl = decoded.holdings[0]
        XCTAssertEqual(aapl.ticker, "AAPL")
        XCTAssertEqual(aapl.isCash, false)
        XCTAssertEqual(aapl.shares, "10")
        XCTAssertEqual(aapl.value, "$1,820.50")
        XCTAssertEqual(aapl.gainLossText, "+$120.50 (7.08%)")
        XCTAssertEqual(aapl.isPositive, true)
        XCTAssertEqual(aapl.daysGain, "+$12.30")
        XCTAssertEqual(aapl.daysGainPercent, "0.68%")
        XCTAssertEqual(aapl.totalGain, "+$120.50")
        XCTAssertEqual(aapl.totalGainPercent, "7.08%")
        XCTAssertEqual(aapl.averageCost, "$170.00")

        let cash = decoded.holdings[1]
        XCTAssertEqual(cash.ticker, "Cash")
        XCTAssertTrue(cash.isCash)
        XCTAssertNil(cash.shares)
        XCTAssertNil(cash.gainLossText)
        XCTAssertNil(cash.isPositive)
        XCTAssertNil(cash.daysGain)
        XCTAssertNil(cash.averageCost)
    }

    func testHoldingDecodesFromExpectedJSONSchema() throws {
        let json = """
        {
            "holdings": [
                {
                    "ticker": "AAPL",
                    "isCash": false,
                    "shares": "10",
                    "value": "$1,820.50",
                    "gainLossText": "+$120.50 (7.08%)",
                    "isPositive": true,
                    "daysGain": "+$12.30",
                    "daysGainPercent": "0.68%",
                    "totalGain": "+$120.50",
                    "totalGainPercent": "7.08%",
                    "averageCost": "$170.00"
                }
            ],
            "displayOption": "Total Value"
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(HoldingsCardData.self, from: json)

        XCTAssertEqual(decoded.displayOption, "Total Value")
        XCTAssertEqual(decoded.holdings.count, 1)
        XCTAssertEqual(decoded.holdings[0].ticker, "AAPL")
        XCTAssertEqual(decoded.holdings[0].averageCost, "$170.00")
    }

    func testHoldingDecodesWithAllOptionalFieldsMissing() throws {
        let json = """
        {
            "holdings": [
                {
                    "ticker": "Cash",
                    "isCash": true,
                    "value": "$250.00"
                }
            ],
            "displayOption": "Total Value"
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(HoldingsCardData.self, from: json)

        XCTAssertEqual(decoded.holdings.count, 1)
        let cash = decoded.holdings[0]
        XCTAssertEqual(cash.ticker, "Cash")
        XCTAssertTrue(cash.isCash)
        XCTAssertEqual(cash.value, "$250.00")
        XCTAssertNil(cash.shares)
        XCTAssertNil(cash.gainLossText)
        XCTAssertNil(cash.isPositive)
        XCTAssertNil(cash.daysGain)
        XCTAssertNil(cash.daysGainPercent)
        XCTAssertNil(cash.totalGain)
        XCTAssertNil(cash.totalGainPercent)
        XCTAssertNil(cash.averageCost)
    }

    func testHoldingIdMatchesTicker() {
        let holding = sampleHoldings[0]
        XCTAssertEqual(holding.id, holding.ticker)
    }
}
