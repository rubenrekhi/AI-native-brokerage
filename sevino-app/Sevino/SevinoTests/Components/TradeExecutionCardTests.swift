import XCTest
@testable import Sevino

@MainActor
final class TradeExecutionCardTests: XCTestCase {

    func testTradeExecutionCardData_codableRoundtrip() throws {
        let original = TradeExecutionCardData(
            side: .buy,
            ticker: "AMD",
            companyName: "Advanced Micro Devices inc.",
            exchange: "NYSE",
            orderType: "Market Order",
            amount: "$500.00",
            estimatedShares: "1.82",
            currentPrice: "$274.63",
            estimatedTotal: "$500.00",
            disclaimer: "Market orders execute at the best available price at market open"
        )

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(TradeExecutionCardData.self, from: data)

        XCTAssertEqual(decoded, original)
    }

    func testTradeSide_decodesFromWireValues() throws {
        let buy = try JSONDecoder().decode(TradeSide.self, from: Data(#""buy""#.utf8))
        let sell = try JSONDecoder().decode(TradeSide.self, from: Data(#""sell""#.utf8))
        XCTAssertEqual(buy, .buy)
        XCTAssertEqual(sell, .sell)
    }

    func testTradeExecutionState_errorEqualityUsesMessage() {
        XCTAssertEqual(TradeExecutionState.error("x"), TradeExecutionState.error("x"))
        XCTAssertNotEqual(TradeExecutionState.error("x"), TradeExecutionState.error("y"))
        XCTAssertNotEqual(TradeExecutionState.pending, TradeExecutionState.success)
    }
}
