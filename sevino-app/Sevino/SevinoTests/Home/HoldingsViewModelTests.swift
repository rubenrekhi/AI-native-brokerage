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

    // MARK: - loadHoldings

    func testLoadHoldingsSuccessPopulatesList() async {
        mockService.holdings = [
            Self.makeHolding(ticker: "AAPL"),
            Self.makeHolding(ticker: "TSLA"),
        ]

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.holdings.count, 2)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadHoldingsAppliesSortOnInitialFetch() async {
        // Server returns positions in arbitrary order; VM sorts on the
        // default (totalValue, highToLow) so the user sees the largest
        // position first without waiting for a manual re-sort.
        mockService.holdings = [
            Self.makeHolding(ticker: "SMALL", marketValue: Decimal(100)),
            Self.makeHolding(ticker: "LARGE", marketValue: Decimal(1000)),
            Self.makeHolding(ticker: "MID", marketValue: Decimal(500)),
        ]

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["LARGE", "MID", "SMALL"])
    }

    // MARK: - Sort option (mechanics)

    func testSetSortOptionUpdatesSelection() {
        viewModel.setSortOption(.alphabetical)

        XCTAssertEqual(viewModel.sortOption, .alphabetical)
    }

    func testSetSortOptionDoesNotTriggerReload() {
        viewModel.setSortOption(.lowToHigh)

        XCTAssertEqual(mockService.fetchHoldingsCallCount, 0,
                       "sort is a local filter; no refetch needed")
    }

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

    private static func makeHolding(
        ticker: String,
        isCash: Bool = false,
        marketValue: Decimal = Decimal(string: "1000.00")!,
        unrealizedPl: Decimal? = Decimal(string: "10.00"),
        changeToday: Decimal? = Decimal(string: "1.00"),
        changeTodayPercent: Decimal? = Decimal(string: "0.0010")
    ) -> Holding {
        Holding(
            ticker: ticker,
            isCash: isCash,
            qty: isCash ? nil : Decimal(10),
            marketValue: marketValue,
            unrealizedPl: isCash ? nil : unrealizedPl,
            unrealizedPlpc: isCash ? nil : Decimal(string: "0.0100"),
            changeToday: isCash ? nil : changeToday,
            changeTodayPercent: isCash ? nil : changeTodayPercent,
            avgEntryPrice: isCash ? nil : Decimal(string: "99.00")!,
            buyingPower: isCash ? Decimal(string: "800.00")! : nil
        )
    }
}

@MainActor
final class HoldingsViewModelSortTests: XCTestCase {

    private var mockService: MockHoldingsService!
    private var viewModel: HoldingsViewModel!

    override func setUp() {
        mockService = MockHoldingsService()
        viewModel = HoldingsViewModel(service: mockService)
    }

    // MARK: - CASH pinning

    func testCashAlwaysPinnedAtIndexZero_regardlessOfSort() async {
        mockService.holdings = [
            makeCash(value: Decimal(50)),
            makePosition(ticker: "TSLA", marketValue: Decimal(2000)),
            makePosition(ticker: "AAPL", marketValue: Decimal(500)),
        ]

        await viewModel.loadHoldings()

        // Default: highToLow + totalValue → TSLA (2000) > AAPL (500), CASH (50) at top
        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["CASH", "TSLA", "AAPL"])

        viewModel.setSortOption(.lowToHigh)
        XCTAssertEqual(viewModel.holdings.first?.isCash, true,
                       "cash stays at index 0 even when sort is low-to-high")

        viewModel.setSortOption(.alphabetical)
        XCTAssertEqual(viewModel.holdings.first?.isCash, true,
                       "cash stays at index 0 even when alphabetical")
    }

    // MARK: - Display option × sort option

    func testTotalValue_highToLow_ordersByMarketValueDescending() async {
        await loadPositions(
            (ticker: "A", mv: Decimal(100)),
            (ticker: "B", mv: Decimal(500)),
            (ticker: "C", mv: Decimal(300))
        )

        viewModel.setDisplayOption(.totalValue)
        viewModel.setSortOption(.highToLow)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["B", "C", "A"])
    }

    func testTotalValue_lowToHigh_ordersByMarketValueAscending() async {
        await loadPositions(
            (ticker: "A", mv: Decimal(100)),
            (ticker: "B", mv: Decimal(500)),
            (ticker: "C", mv: Decimal(300))
        )

        viewModel.setDisplayOption(.totalValue)
        viewModel.setSortOption(.lowToHigh)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["A", "C", "B"])
    }

    func testAllTimeReturn_highToLow_ordersByUnrealizedPl() async {
        mockService.holdings = [
            makePosition(ticker: "A", unrealizedPl: Decimal(50)),
            makePosition(ticker: "B", unrealizedPl: Decimal(-10)),
            makePosition(ticker: "C", unrealizedPl: Decimal(200)),
        ]
        await viewModel.loadHoldings()

        viewModel.setDisplayOption(.allTimeReturn)
        viewModel.setSortOption(.highToLow)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["C", "A", "B"])
    }

    func testTodaysReturn_highToLow_ordersByChangeToday() async {
        mockService.holdings = [
            makePosition(ticker: "A", changeToday: Decimal(5)),
            makePosition(ticker: "B", changeToday: Decimal(-2)),
            makePosition(ticker: "C", changeToday: Decimal(50)),
        ]
        await viewModel.loadHoldings()

        viewModel.setDisplayOption(.todaysReturn)
        viewModel.setSortOption(.highToLow)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["C", "A", "B"])
    }

    func testPriceChange_highToLow_ordersByChangeTodayPercent() async {
        mockService.holdings = [
            makePosition(ticker: "A", changeTodayPct: Decimal(string: "0.01")!),
            makePosition(ticker: "B", changeTodayPct: Decimal(string: "-0.05")!),
            makePosition(ticker: "C", changeTodayPct: Decimal(string: "0.10")!),
        ]
        await viewModel.loadHoldings()

        viewModel.setDisplayOption(.priceChange)
        viewModel.setSortOption(.highToLow)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["C", "A", "B"])
    }

    // MARK: - Alphabetical override

    func testAlphabetical_overridesDisplayKey() async {
        // Positions ordered by marketValue descending in the fixture, but
        // alphabetical sort should ignore the display key entirely and
        // order by ticker ascending.
        await loadPositions(
            (ticker: "ZZZ", mv: Decimal(1000)),
            (ticker: "AAA", mv: Decimal(500)),
            (ticker: "MMM", mv: Decimal(100))
        )

        viewModel.setDisplayOption(.totalValue) // would normally drive ZZZ→AAA→MMM
        viewModel.setSortOption(.alphabetical)

        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["AAA", "MMM", "ZZZ"])
    }

    func testAlphabetical_independentOfDisplayOption() async {
        await loadPositions(
            (ticker: "B", mv: Decimal(100)),
            (ticker: "A", mv: Decimal(500))
        )

        viewModel.setSortOption(.alphabetical)

        // Switching displayOption while alphabetical is active should
        // not change the order (alphabetical doesn't read the display key).
        viewModel.setDisplayOption(.allTimeReturn)
        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["A", "B"])

        viewModel.setDisplayOption(.priceChange)
        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["A", "B"])
    }

    // MARK: - Re-sort triggers

    func testChangingDisplayOption_reordersImmediately() async {
        mockService.holdings = [
            makePosition(ticker: "BIG_VAL", marketValue: Decimal(1000), unrealizedPl: Decimal(10)),
            makePosition(ticker: "BIG_PL", marketValue: Decimal(100), unrealizedPl: Decimal(500)),
        ]
        await viewModel.loadHoldings()
        XCTAssertEqual(viewModel.holdings.first?.ticker, "BIG_VAL")

        viewModel.setDisplayOption(.allTimeReturn)
        XCTAssertEqual(viewModel.holdings.first?.ticker, "BIG_PL")
    }

    func testChangingSortDirection_flipsOrder() async {
        await loadPositions(
            (ticker: "A", mv: Decimal(100)),
            (ticker: "B", mv: Decimal(500))
        )

        viewModel.setSortOption(.highToLow)
        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["B", "A"])

        viewModel.setSortOption(.lowToHigh)
        XCTAssertEqual(viewModel.holdings.map(\.ticker), ["A", "B"])
    }

    // MARK: - Edge cases

    func testEmptyPositions_sortDoesNotCrash() async {
        mockService.holdings = [makeCash(value: Decimal(100))]

        await viewModel.loadHoldings()
        viewModel.setSortOption(.alphabetical)
        viewModel.setDisplayOption(.todaysReturn)

        XCTAssertEqual(viewModel.holdings.count, 1)
        XCTAssertEqual(viewModel.holdings[0].ticker, "CASH")
    }

    // MARK: - Helpers

    private func loadPositions(_ specs: (ticker: String, mv: Decimal)...) async {
        mockService.holdings = specs.map { makePosition(ticker: $0.ticker, marketValue: $0.mv) }
        await viewModel.loadHoldings()
    }

    private func makeCash(value: Decimal) -> Holding {
        Holding(
            ticker: "CASH",
            isCash: true,
            qty: nil,
            marketValue: value,
            unrealizedPl: nil,
            unrealizedPlpc: nil,
            changeToday: nil,
            changeTodayPercent: nil,
            avgEntryPrice: nil,
            buyingPower: value
        )
    }

    private func makePosition(
        ticker: String,
        marketValue: Decimal = Decimal(100),
        unrealizedPl: Decimal = Decimal(0),
        changeToday: Decimal = Decimal(0),
        changeTodayPct: Decimal = Decimal(0)
    ) -> Holding {
        Holding(
            ticker: ticker,
            isCash: false,
            qty: Decimal(1),
            marketValue: marketValue,
            unrealizedPl: unrealizedPl,
            unrealizedPlpc: Decimal(0),
            changeToday: changeToday,
            changeTodayPercent: changeTodayPct,
            avgEntryPrice: Decimal(100),
            buyingPower: nil
        )
    }
}
