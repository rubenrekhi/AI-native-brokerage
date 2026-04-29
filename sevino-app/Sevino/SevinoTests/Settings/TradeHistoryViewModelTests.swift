import XCTest
@testable import Sevino

@MainActor
final class TradeHistoryViewModelTests: XCTestCase {

    private func makeSUT(
        mock: MockTradingService = MockTradingService()
    ) -> (TradeHistoryViewModel, MockTradingService) {
        (TradeHistoryViewModel(tradingService: mock), mock)
    }

    private func makeOrder(
        id: String,
        symbol: String = "AAPL",
        side: String = "buy",
        status: String = "filled",
        submittedAt: String? = nil,
        filledAt: String? = nil,
        canceledAt: String? = nil,
        failedAt: String? = nil,
        qty: String? = "10",
        filledQty: String? = "10",
        filledAvgPrice: String? = "100"
    ) -> OrderResponse {
        OrderResponse(
            id: id,
            clientOrderId: nil,
            symbol: symbol,
            assetClass: "us_equity",
            side: side,
            orderType: "market",
            timeInForce: "day",
            qty: qty,
            notional: nil,
            filledQty: filledQty,
            filledAvgPrice: filledAvgPrice,
            limitPrice: nil,
            stopPrice: nil,
            status: status,
            submittedAt: submittedAt,
            filledAt: filledAt,
            canceledAt: canceledAt,
            expiredAt: nil,
            failedAt: failedAt,
            createdAt: submittedAt
        )
    }

    private func makePosition(symbol: String) -> PositionResponse {
        PositionResponse(symbol: symbol, assetClass: "us_equity", qty: "1", marketValue: "100")
    }

    // MARK: - load

    func test_load_sortsOrdersByRepresentativeDateDescending() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "old", status: "filled", filledAt: "2026-01-01T10:00:00Z"),
            makeOrder(id: "new", status: "filled", filledAt: "2026-04-22T15:30:00Z"),
            makeOrder(id: "mid", status: "filled", filledAt: "2026-02-15T10:00:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(sut.orders.map(\.id), ["new", "mid", "old"])
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.error)
    }

    func test_load_placesNilDatesAfterDatedEntries() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "nodate", status: "filled", filledAt: nil, qty: nil, filledQty: nil, filledAvgPrice: nil),
            makeOrder(id: "dated", status: "filled", filledAt: "2026-04-22T15:30:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(sut.orders.first?.id, "dated")
    }

    func test_load_failureSurfacesErrorAndKeepsOrdersEmpty() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .failure(TestError.boom)

        await sut.load()

        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)
        XCTAssertFalse(sut.isLoading)
        XCTAssertTrue(sut.orders.isEmpty)
    }

    func test_load_clearsPriorErrorOnSuccess() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertNotNil(sut.error)

        mock.listOrdersResult = .success([
            makeOrder(id: "t", filledAt: "2026-04-22T15:30:00Z"),
        ])
        await sut.load()

        XCTAssertNil(sut.error)
        XCTAssertEqual(sut.orders.count, 1)
    }

    func test_load_populatesPositions() async {
        let (sut, mock) = makeSUT()
        mock.listPositionsResult = .success([
            makePosition(symbol: "TSLA"),
            makePosition(symbol: "AAPL"),
        ])

        await sut.load()

        XCTAssertEqual(sut.positions.map(\.symbol), ["TSLA", "AAPL"])
        XCTAssertEqual(sut.holdingsSymbols, ["AAPL", "TSLA"])
    }

    // MARK: - filteredOrders

    func test_filteredOrders_bucketsPartiallyFilledIntoPending() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "filled", status: "filled", filledAt: "2026-04-22T15:30:00Z"),
            makeOrder(id: "partial", status: "partially_filled", submittedAt: "2026-04-21T18:00:00Z"),
            makeOrder(id: "rejected", status: "rejected", failedAt: "2026-04-19T10:05:00Z"),
        ])

        await sut.load()

        sut.statusFilter = .pending
        XCTAssertEqual(sut.filteredOrders.map(\.id), ["partial"])

        sut.statusFilter = .completed
        XCTAssertEqual(sut.filteredOrders.map(\.id), ["filled"])

        sut.statusFilter = .failed
        XCTAssertEqual(sut.filteredOrders.map(\.id), ["rejected"])
    }

    func test_filteredOrders_allReturnsEverything() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "a", status: "filled", filledAt: "2026-04-22T15:30:00Z"),
            makeOrder(id: "b", status: "rejected", failedAt: "2026-04-19T10:05:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(Set(sut.filteredOrders.map(\.id)), Set(["a", "b"]))
    }

    // MARK: - filter side effects

    func test_statusFilterChange_triggersReload() async {
        let (sut, mock) = makeSUT()
        await sut.load()
        let baseline = mock.listOrdersCalls.count

        sut.statusFilter = .pending

        // Wait for the spawned reload to settle.
        await Task.yield()
        try? await Task.sleep(nanoseconds: 10_000_000)

        XCTAssertGreaterThan(mock.listOrdersCalls.count, baseline)
        XCTAssertEqual(mock.listOrdersCalls.last?.status, "open")
    }

    func test_holdingsFilterPropagatesAsSymbolsQueryParam() async {
        let (sut, mock) = makeSUT()
        await sut.load()

        sut.holdingsFilter = "TSLA"
        await Task.yield()
        try? await Task.sleep(nanoseconds: 10_000_000)

        XCTAssertEqual(mock.listOrdersCalls.last?.symbols, "TSLA")
    }

    func test_setSameFilterValue_doesNotTriggerReload() async {
        let (sut, mock) = makeSUT()
        await sut.load()
        let baseline = mock.listOrdersCalls.count

        sut.statusFilter = .all  // same as initial
        await Task.yield()

        XCTAssertEqual(mock.listOrdersCalls.count, baseline)
    }

    // MARK: - isShowingError

    func test_isShowingError_falseWhenNoError() {
        let (sut, _) = makeSUT()
        XCTAssertFalse(sut.isShowingError)
    }

    func test_isShowingError_falseWhenErrorButNoCachedOrders() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertTrue(sut.orders.isEmpty)
        XCTAssertFalse(sut.isShowingError)
    }

    func test_isShowingError_trueWhenErrorFollowsSuccessfulLoad() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "t", filledAt: "2026-04-22T15:30:00Z"),
        ])
        await sut.load()
        mock.listOrdersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertFalse(sut.orders.isEmpty)
        XCTAssertTrue(sut.isShowingError)
    }

    func test_isShowingError_settingFalseClearsError() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .success([
            makeOrder(id: "t", filledAt: "2026-04-22T15:30:00Z"),
        ])
        await sut.load()
        mock.listOrdersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertTrue(sut.isShowingError)

        sut.isShowingError = false

        XCTAssertNil(sut.error)
        XCTAssertFalse(sut.isShowingError)
    }

    // MARK: - clearError

    func test_clearError_resetsError() async {
        let (sut, mock) = makeSUT()
        mock.listOrdersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertNotNil(sut.error)

        sut.clearError()

        XCTAssertNil(sut.error)
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "boom" }
    }
}
