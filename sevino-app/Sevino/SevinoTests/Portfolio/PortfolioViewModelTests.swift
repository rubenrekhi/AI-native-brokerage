import XCTest
@testable import Sevino

@MainActor
final class PortfolioViewModelTests: XCTestCase {

    private var mockService: MockPortfolioService!
    private var mockHistoryService: MockPortfolioHistoryService!
    private var viewModel: PortfolioViewModel!

    override func setUp() {
        mockService = MockPortfolioService()
        mockHistoryService = MockPortfolioHistoryService()
        viewModel = PortfolioViewModel(
            service: mockService,
            historyService: mockHistoryService
        )
    }

    // MARK: - Initial state

    func testInitialStateDefaultsToOneMonth() {
        XCTAssertEqual(viewModel.selectedTimeRange, .oneMonth)
        XCTAssertEqual(viewModel.displayValue, "—")
        XCTAssertEqual(viewModel.gainText, "")
        XCTAssertTrue(viewModel.chartPoints.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadPortfolio success

    func testLoadPortfolioSuccessPopulatesSnapshotAndHistory() async {
        mockService.snapshot = PortfolioSnapshot(
            accountStatus: "ACTIVE",
            equity: Decimal(string: "2500.00")!,
            dailyChangeAbs: Decimal(string: "42.00")!,
            dailyChangePct: Decimal(string: "0.0170")!,
            chartPoints: []
        )
        mockHistoryService.series = Self.makeSeries(chartPoints: [0.1, 0.5, 0.9])

        await viewModel.loadPortfolio()

        // Locale-agnostic — `Locale.current` differs between simulators (iPhone 17
        // formats USD as `US$2,500.00`, iPhone 16 as `$2,500.00`). Until
        // NumberFormatting accepts an injected locale, assert on the digit
        // groups rather than the full formatted string.
        XCTAssertTrue(viewModel.displayValue.contains("2,500"),
                      "snapshot equity should appear in displayValue")
        XCTAssertFalse(viewModel.isDown)
        XCTAssertTrue(viewModel.gainText.contains("42") && viewModel.gainText.contains("1.70"),
                      "snapshot daily change should appear in gainText")
        XCTAssertEqual(viewModel.chartPoints, [0.1, 0.5, 0.9],
                       "chartPoints come from the history service, not the snapshot")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadPortfolioCopiesIsDownTrueFromSnapshot() async {
        mockService.snapshot = PortfolioSnapshot(
            accountStatus: "ACTIVE",
            equity: Decimal(string: "900.00")!,
            dailyChangeAbs: Decimal(string: "-100.00")!,
            dailyChangePct: Decimal(string: "-0.1000")!,
            chartPoints: []
        )

        await viewModel.loadPortfolio()

        XCTAssertTrue(viewModel.isDown, "isDown must reflect the snapshot, not the default")
    }

    func testLoadPortfolioPassesSelectedTimeRangeToBothServices() async {
        viewModel.setTimeRange(.oneYear)

        await viewModel.loadPortfolio()

        XCTAssertEqual(mockService.fetchPortfolioRanges, [.oneYear])
        XCTAssertEqual(mockHistoryService.fetchHistoryRanges, [.oneYear])
    }

    func testLoadPortfolioWithoutSetTimeRangePassesDefaultOneMonth() async {
        await viewModel.loadPortfolio()

        XCTAssertEqual(mockService.fetchPortfolioRanges, [.oneMonth])
        XCTAssertEqual(mockHistoryService.fetchHistoryRanges, [.oneMonth])
    }

    // MARK: - loadHistory (range-only refresh)

    func testLoadHistoryUpdatesChartPointsWithoutRefetchingSnapshot() async {
        mockHistoryService.series = Self.makeSeries(chartPoints: [0.2, 0.4, 0.6])

        await viewModel.loadHistory()

        XCTAssertEqual(viewModel.chartPoints, [0.2, 0.4, 0.6])
        XCTAssertEqual(mockService.fetchPortfolioCallCount, 0,
                       "loadHistory must not refetch the snapshot — pill numbers stay stable")
        XCTAssertEqual(mockHistoryService.fetchHistoryCallCount, 1)
    }

    func testLoadHistoryFailureLeavesChartPointsUnchanged() async {
        mockHistoryService.series = Self.makeSeries(chartPoints: [0.1, 0.2])
        await viewModel.loadHistory()
        XCTAssertEqual(viewModel.chartPoints, [0.1, 0.2])

        mockHistoryService.fetchHistoryError = NSError(domain: "test", code: 0)
        await viewModel.loadHistory()

        XCTAssertEqual(viewModel.chartPoints, [0.1, 0.2],
                       "history errors should not wipe the previously-shown chart")
    }

    // MARK: - Time range selection

    func testSetTimeRangeUpdatesSelectionWithoutFetching() {
        viewModel.setTimeRange(.sixMonths)

        XCTAssertEqual(viewModel.selectedTimeRange, .sixMonths)
        XCTAssertEqual(mockService.fetchPortfolioCallCount, 0,
                       "setTimeRange is synchronous; callers own the fetch via .task(id:)")
        XCTAssertEqual(mockHistoryService.fetchHistoryCallCount, 0)
    }

    func testSetTimeRangeUpdatesPeriodLabel() {
        viewModel.setTimeRange(.ytd)

        XCTAssertEqual(viewModel.periodLabel, TimeRange.ytd.periodLabel)
    }

    // MARK: - Error path

    func testLoadPortfolioFailureSurfacesSnapshotError() async {
        mockService.fetchPortfolioError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.loadPortfolio()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testLoadPortfolioRetrySuccessClearsError() async {
        mockService.fetchPortfolioError = NSError(domain: "test", code: 0)
        await viewModel.loadPortfolio()
        XCTAssertNotNil(viewModel.error)

        mockService.fetchPortfolioError = nil
        await viewModel.loadPortfolio()

        XCTAssertNil(viewModel.error)
    }

    func testLoadPortfolioHistoryFailureDoesNotSurfaceError() async {
        mockHistoryService.fetchHistoryError = NSError(domain: "test", code: 0)

        await viewModel.loadPortfolio()

        XCTAssertNil(viewModel.error,
                     "history errors are silent in F4.8 — F4.10 will add explicit chart UI")
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockService.fetchPortfolioError = NSError(domain: "test", code: 0)
        await viewModel.loadPortfolio()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Helpers

    private static func makeSeries(chartPoints: [Double]) -> PortfolioHistorySeries {
        PortfolioHistorySeries(
            range: .oneMonth,
            baseValue: Decimal(0),
            endValue: Decimal(0),
            gainAbs: Decimal(0),
            gainPct: Decimal(0),
            points: [],
            chartPoints: chartPoints
        )
    }
}
