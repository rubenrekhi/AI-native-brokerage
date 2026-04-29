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
        XCTAssertEqual(viewModel.accountStatus, "")
        XCTAssertEqual(viewModel.displayOption, .totalValue)
        XCTAssertEqual(viewModel.sortOption, .highToLow)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - accountStatus exposure (F4.10)

    func testLoadHoldingsExposesAccountStatusFromService() async {
        mockService.accountStatus = "APPROVAL_PENDING"
        mockService.holdings = []

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.accountStatus, "APPROVAL_PENDING",
                       "VM must surface the DTO's accountStatus so the view can pick the right empty/pending state")
    }

    func testLoadHoldingsFailurePreservesPriorAccountStatus() async {
        mockService.accountStatus = "ACTIVE"
        mockService.holdings = [Self.makeHolding(ticker: "AAPL")]
        await viewModel.loadHoldings()
        XCTAssertEqual(viewModel.accountStatus, "ACTIVE")

        mockService.fetchHoldingsError = NSError(domain: "test", code: 0)
        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.accountStatus, "ACTIVE",
                       "transient failures must not wipe the last-known status")
    }

    func testLoadHoldingsParsesAccountStatusFromAccountNotActiveError() async {
        mockService.fetchHoldingsError = APIError(
            error: "Your brokerage account is not active yet.",
            code: APIError.Code.accountNotActive,
            detail: ["account_status": AnyCodable("APPROVAL_PENDING")]
        )

        await viewModel.loadHoldings()

        XCTAssertEqual(viewModel.accountStatus, "APPROVAL_PENDING",
                       "VM must extract account_status from a 409 detail so the pending UI can render")
        XCTAssertNil(viewModel.error,
                     "ACCOUNT_NOT_ACTIVE is not a generic error — accountStatus carries the meaning")
    }

    func testLoadHoldingsSuppressesErrorAfterFirstSuccess() async {
        mockService.accountStatus = "ACTIVE"
        mockService.holdings = [Self.makeHolding(ticker: "AAPL")]
        await viewModel.loadHoldings()
        XCTAssertEqual(viewModel.accountStatus, "ACTIVE")

        mockService.fetchHoldingsError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )
        await viewModel.loadHoldings()

        XCTAssertNil(viewModel.error,
                     "stale-while-error: refresh failures stay silent so the last good list remains on screen")
        XCTAssertEqual(viewModel.accountStatus, "ACTIVE")
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

    private static func makeHolding(ticker: String) -> PortfolioHolding {
        PortfolioHolding(
            ticker: ticker, isCash: false, name: ticker,
            qty: Decimal(10), marketValue: Decimal(1000),
            avgEntryPrice: Decimal(99),
            unrealizedPl: Decimal(10),
            unrealizedPlpc: Decimal(string: "0.01")!
        )
    }
}
