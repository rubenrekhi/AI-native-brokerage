import XCTest
@testable import Sevino

@MainActor
final class FundingViewModelTests: XCTestCase {

    private var mockService: MockFundingService!
    private var viewModel: FundingViewModel!

    override func setUp() {
        mockService = MockFundingService()
        viewModel = FundingViewModel(service: mockService)
    }

    // MARK: - Initial state

    func testInitialStateAllFieldsDefaultToDash() {
        XCTAssertEqual(viewModel.cashBalance, "—")
        XCTAssertEqual(viewModel.cashApy, "—")
        XCTAssertEqual(viewModel.cashThisMonth, "—")
        XCTAssertEqual(viewModel.cashDaysAccrued, "—")
        XCTAssertEqual(viewModel.cashLifetime, "—")
        XCTAssertEqual(viewModel.cashLifetimeSince, "—")
        XCTAssertEqual(viewModel.cashBuyingPower, "—")
        XCTAssertEqual(viewModel.cashPendingDeposits, "—")
        XCTAssertEqual(viewModel.cashInterestPaidOut, "—")
        XCTAssertEqual(viewModel.cashFdicInsured, "—")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadFundingData success

    func testLoadFundingDataSuccessPopulatesAllFields() async {
        mockService.snapshot = FundingSnapshot(
            cashBalance: "$500.00",
            cashApy: "4.00%",
            cashThisMonth: "+$2.00",
            cashDaysAccrued: "15",
            cashLifetime: "+$20.00",
            cashLifetimeSince: "Mar 2026",
            cashBuyingPower: "$500.00",
            cashPendingDeposits: "$50.00",
            cashInterestPaidOut: "Monthly",
            cashFdicInsured: "$2,500,000"
        )

        await viewModel.loadFundingData()

        XCTAssertEqual(viewModel.cashBalance, "$500.00")
        XCTAssertEqual(viewModel.cashApy, "4.00%")
        XCTAssertEqual(viewModel.cashThisMonth, "+$2.00")
        XCTAssertEqual(viewModel.cashDaysAccrued, "15")
        XCTAssertEqual(viewModel.cashLifetime, "+$20.00")
        XCTAssertEqual(viewModel.cashLifetimeSince, "Mar 2026")
        XCTAssertEqual(viewModel.cashBuyingPower, "$500.00")
        XCTAssertEqual(viewModel.cashPendingDeposits, "$50.00")
        XCTAssertEqual(viewModel.cashInterestPaidOut, "Monthly")
        XCTAssertEqual(viewModel.cashFdicInsured, "$2,500,000")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadFundingDataCallsServiceOnce() async {
        await viewModel.loadFundingData()

        XCTAssertEqual(mockService.fetchFundingCallCount, 1)
    }

    // MARK: - Error path

    func testLoadFundingDataFailureSurfacesError() async {
        mockService.fetchFundingError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.loadFundingData()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testLoadFundingDataFailureLeavesFieldsUnchangedFromPreviousSuccess() async {
        // Seed a distinctive snapshot so the assertion proves retention,
        // not just "cashBalance was never mutated."
        mockService.snapshot = FundingSnapshot(
            cashBalance: "$777.77",
            cashApy: "4.00%",
            cashThisMonth: "+$2.00",
            cashDaysAccrued: "15",
            cashLifetime: "+$20.00",
            cashLifetimeSince: "Mar 2026",
            cashBuyingPower: "$777.77",
            cashPendingDeposits: "$50.00",
            cashInterestPaidOut: "Monthly",
            cashFdicInsured: "$2,500,000"
        )
        await viewModel.loadFundingData()
        XCTAssertEqual(viewModel.cashBalance, "$777.77", "sanity: first success populated fields")

        mockService.fetchFundingError = NSError(domain: "test", code: 0)
        await viewModel.loadFundingData()

        XCTAssertEqual(viewModel.cashBalance, "$777.77",
                       "a failed refresh should not clobber the last successful snapshot")
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockService.fetchFundingError = NSError(domain: "test", code: 0)
        await viewModel.loadFundingData()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }
}
