import XCTest
@testable import Sevino

@MainActor
final class PortfolioViewModelTests: XCTestCase {

    private var mockService: MockPortfolioService!
    private var viewModel: PortfolioViewModel!

    override func setUp() {
        mockService = MockPortfolioService()
        viewModel = PortfolioViewModel(service: mockService)
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

    func testLoadPortfolioSuccessPopulatesSnapshotFields() async {
        mockService.snapshot = PortfolioSnapshot(
            accountStatus: "ACTIVE",
            equity: Decimal(string: "2500.00")!,
            dailyChangeAbs: Decimal(string: "42.00")!,
            dailyChangePct: Decimal(string: "0.0170")!,
            chartPoints: [0.1, 0.5, 0.9]
        )

        await viewModel.loadPortfolio()

        XCTAssertEqual(viewModel.displayValue, "$2,500.00")
        XCTAssertFalse(viewModel.isDown)
        XCTAssertEqual(viewModel.gainText, "+$42.00 (+1.70%)")
        XCTAssertEqual(viewModel.chartPoints, [0.1, 0.5, 0.9])
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadPortfolioCopiesIsDownTrueFromSnapshot() async {
        mockService.snapshot = PortfolioSnapshot(
            accountStatus: "ACTIVE",
            equity: Decimal(string: "900.00")!,
            dailyChangeAbs: Decimal(string: "-100.00")!,
            dailyChangePct: Decimal(string: "-0.1000")!,
            chartPoints: [0.9, 0.5, 0.1]
        )

        await viewModel.loadPortfolio()

        XCTAssertTrue(viewModel.isDown, "isDown must reflect the snapshot, not the default")
    }

    func testLoadPortfolioPassesSelectedTimeRangeToService() async {
        viewModel.setTimeRange(.oneYear)

        await viewModel.loadPortfolio()

        XCTAssertEqual(mockService.fetchPortfolioRanges, [.oneYear])
    }

    func testLoadPortfolioWithoutSetTimeRangePassesDefaultOneMonth() async {
        await viewModel.loadPortfolio()

        XCTAssertEqual(mockService.fetchPortfolioRanges, [.oneMonth])
    }

    // MARK: - Time range selection

    func testSetTimeRangeUpdatesSelectionWithoutFetching() {
        viewModel.setTimeRange(.sixMonths)

        XCTAssertEqual(viewModel.selectedTimeRange, .sixMonths)
        XCTAssertEqual(mockService.fetchPortfolioCallCount, 0,
                       "setTimeRange is synchronous; callers own the fetch via .task(id:)")
    }

    func testSetTimeRangeUpdatesPeriodLabel() {
        viewModel.setTimeRange(.ytd)

        XCTAssertEqual(viewModel.periodLabel, TimeRange.ytd.periodLabel)
    }

    // MARK: - Error path

    func testLoadPortfolioFailureSurfacesError() async {
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

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockService.fetchPortfolioError = NSError(domain: "test", code: 0)
        await viewModel.loadPortfolio()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }
}
