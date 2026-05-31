import XCTest
@testable import Sevino

final class RadarCardDataTests: XCTestCase {

    func testNewTabStateIsPopulatedWhenNewItemsExist() {
        let data = RadarCardData(
            newItems: [Self.item(ticker: "NVDA")],
            starredItems: [],
            nextRefreshWeekday: "Monday"
        )

        XCTAssertEqual(data.newTabState, .populated)
    }

    func testNewTabStateIsReviewedWhenEmptyWithFutureAnchor() {
        let data = RadarCardData(
            newItems: [],
            starredItems: [Self.item(ticker: "AAPL")],
            nextRefreshWeekday: "Thursday"
        )

        XCTAssertEqual(data.newTabState, .reviewed(weekday: "Thursday"))
    }

    func testNewTabStateIsFirstBatchWhenEmptyWithoutAnchor() {
        let data = RadarCardData(newItems: [], starredItems: [], nextRefreshWeekday: nil)

        XCTAssertEqual(data.newTabState, .firstBatch)
    }

    private static func item(ticker: String) -> RadarItem {
        RadarItem(
            ticker: ticker,
            description: "desc",
            isStarred: false,
            price: "$1.00",
            changePercent: "+1.00%",
            isPositive: true,
            expiresIn: ""
        )
    }
}
