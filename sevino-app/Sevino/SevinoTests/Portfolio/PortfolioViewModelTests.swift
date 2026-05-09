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
        XCTAssertEqual(viewModel.equity, 0)
        XCTAssertEqual(viewModel.gainAbs, 0)
        XCTAssertEqual(viewModel.gainPct, 0)
        XCTAssertEqual(viewModel.currency, "USD")
        XCTAssertTrue(viewModel.chartPoints.isEmpty)
        XCTAssertTrue(viewModel.chartValues.isEmpty)
        XCTAssertTrue(viewModel.chartDates.isEmpty)
        XCTAssertFalse(viewModel.hasLoaded)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadPortfolio success

    func testLoadPortfolioSuccessPopulatesSnapshotFields() async {
        let dates = [
            Date(timeIntervalSince1970: 1700000000),
            Date(timeIntervalSince1970: 1700001000),
            Date(timeIntervalSince1970: 1700002000)
        ]
        mockService.snapshot = PortfolioSnapshot(
            equity: Decimal(string: "2500.00")!,
            currency: "USD",
            gainAbs: Decimal(string: "42.00")!,
            gainPct: Decimal(string: "0.0170")!,
            chartPoints: [0.1, 0.5, 0.9],
            chartValues: [Decimal(2400), Decimal(2450), Decimal(2500)],
            chartDates: dates
        )

        await viewModel.loadPortfolio()

        XCTAssertEqual(viewModel.equity, Decimal(string: "2500.00"))
        XCTAssertEqual(viewModel.currency, "USD")
        XCTAssertEqual(viewModel.gainAbs, Decimal(string: "42.00"))
        XCTAssertEqual(viewModel.gainPct, Decimal(string: "0.0170"))
        XCTAssertEqual(viewModel.chartPoints, [0.1, 0.5, 0.9])
        XCTAssertEqual(viewModel.chartValues, [Decimal(2400), Decimal(2450), Decimal(2500)])
        XCTAssertEqual(viewModel.chartDates, dates)
        XCTAssertTrue(viewModel.hasLoaded)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadPortfolioCopiesNegativeGainFromSnapshot() async {
        mockService.snapshot = PortfolioSnapshot(
            equity: Decimal(string: "900.00")!,
            currency: "USD",
            gainAbs: Decimal(string: "-100.00")!,
            gainPct: Decimal(string: "-0.10")!,
            chartPoints: [0.9, 0.5, 0.1],
            chartValues: [Decimal(1000), Decimal(950), Decimal(900)],
            chartDates: [
                Date(timeIntervalSince1970: 1700000000),
                Date(timeIntervalSince1970: 1700001000),
                Date(timeIntervalSince1970: 1700002000)
            ]
        )

        await viewModel.loadPortfolio()

        XCTAssertEqual(viewModel.gainAbs, Decimal(string: "-100.00"))
        XCTAssertEqual(viewModel.gainPct, Decimal(string: "-0.10"))
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

    func testLoadPortfolioSetsHasLoadedTrue() async {
        XCTAssertFalse(viewModel.hasLoaded)

        await viewModel.loadPortfolio()

        XCTAssertTrue(viewModel.hasLoaded)
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

    func testLoadPortfolioErrorPreservesLastGoodHasLoaded() async {
        await viewModel.loadPortfolio()
        XCTAssertTrue(viewModel.hasLoaded)

        mockService.fetchPortfolioError = NSError(domain: "test", code: 0)
        await viewModel.loadPortfolio()

        XCTAssertNotNil(viewModel.error)
        XCTAssertTrue(viewModel.hasLoaded,
                      "hasLoaded must stay true on retry failure so last-good data stays visible")
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
