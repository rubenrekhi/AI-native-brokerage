import XCTest
@testable import Sevino

@MainActor
final class HoldingsViewModelTests: XCTestCase {

    private var mockService: MockHoldingsService!
    private var viewModel: HoldingsViewModel!

    override func setUp() {
        mockService = MockHoldingsService()
        viewModel = HoldingsViewModel(service: mockService)
    }

    // MARK: - Initial state

    func testInitialStateDefaultsToTotalValueAndHighToLow() {
        XCTAssertTrue(viewModel.holdings.isEmpty)
        XCTAssertEqual(viewModel.displayOption, .totalValue)
        XCTAssertEqual(viewModel.sortOption, .highToLow)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadHoldings success

    func testLoadHoldingsSuccessPopulatesList() async {
        mockService.holdings = [
            Self.makeHolding(ticker: "AAPL"),
            Self.makeHolding(ticker: "TSLA"),
        ]

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["AAPL", "TSLA"])
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadHoldingsPreservesServiceOrder() async {
        mockService.holdings = [
            Self.makeHolding(ticker: "ZZZ"),
            Self.makeHolding(ticker: "AAA"),
            Self.makeHolding(ticker: "MMM"),
        ]

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["ZZZ", "AAA", "MMM"],
                       "sorting is a view-layer concern; VM mirrors server order")
    }

    // MARK: - Sort option

    func testSetSortOptionUpdatesSelection() {
        viewModel.setSortOption(.alphabetical)

        XCTAssertEqual(viewModel.sortOption, .alphabetical)
    }

    func testSetSortOptionDoesNotTriggerReload() {
        viewModel.setSortOption(.lowToHigh)

        XCTAssertEqual(mockService.fetchHoldingsCallCount, 0,
                       "sort is a local filter; no refetch needed")
    }

    // MARK: - Display option

    func testSetDisplayOptionUpdatesSelection() {
        viewModel.setDisplayOption(.allTimeReturn)

        XCTAssertEqual(viewModel.displayOption, .allTimeReturn)
    }

    func testSetDisplayOptionDoesNotTriggerReload() {
        viewModel.setDisplayOption(.allTimeReturn)

        XCTAssertEqual(mockService.fetchHoldingsCallCount, 0,
                       "display option is a local filter; no refetch needed")
    }

    // MARK: - Error path

    func testLoadHoldingsFailureSurfacesError() async {
        mockService.fetchHoldingsError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertTrue(viewModel.holdings.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockService.fetchHoldingsError = NSError(domain: "test", code: 0)
        await viewModel.loadHoldings()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Helpers

    private static func makeHolding(ticker: String) -> Holding {
        Holding(
            ticker: ticker,
            isCash: false,
            qty: Decimal(10),
            marketValue: Decimal(string: "1000.00")!,
            unrealizedPl: Decimal(string: "10.00")!,
            unrealizedPlpc: Decimal(string: "0.0100")!,
            changeToday: Decimal(string: "1.00")!,
            changeTodayPercent: Decimal(string: "0.0010")!,
            avgEntryPrice: Decimal(string: "99.00")!
        )
    }
}
