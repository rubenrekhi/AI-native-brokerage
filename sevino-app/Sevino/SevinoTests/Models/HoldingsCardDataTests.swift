import XCTest
@testable import Sevino

final class HoldingsCardDataTests: XCTestCase {

    func testHoldingIdMatchesTicker() {
        let holding = Holding(
            ticker: "AAPL",
            isCash: false,
            qty: Decimal(10),
            marketValue: Decimal(string: "1820.50")!,
            unrealizedPl: Decimal(string: "120.50")!,
            unrealizedPlpc: Decimal(string: "0.0708")!,
            changeToday: Decimal(string: "12.30")!,
            changeTodayPercent: Decimal(string: "0.0068")!,
            avgEntryPrice: Decimal(string: "170.00")!,
            buyingPower: nil
        )

        XCTAssertEqual(holding.id, holding.ticker)
        XCTAssertEqual(holding.id, "AAPL")
    }

    func testHoldingsAreEquatableByValue() {
        let a = Holding(
            ticker: "TSLA",
            isCash: false,
            qty: Decimal(5),
            marketValue: Decimal(string: "1250.00")!,
            unrealizedPl: Decimal(string: "250.00")!,
            unrealizedPlpc: Decimal(string: "0.25")!,
            changeToday: Decimal(string: "25.00")!,
            changeTodayPercent: Decimal(string: "0.0204")!,
            avgEntryPrice: Decimal(string: "200.00")!,
            buyingPower: nil
        )
        let b = a

        XCTAssertEqual(a, b)
    }
}
