import XCTest
@testable import Sevino

@MainActor
final class CashEnrollmentStatusViewModelTests: XCTestCase {

    private var mockFunding: MockFundingService!
    private var viewModel: CashEnrollmentStatusViewModel!

    override func setUp() {
        mockFunding = MockFundingService()
        viewModel = CashEnrollmentStatusViewModel(service: mockFunding)
    }

    // MARK: - load

    func testLoadHydratesState() async {
        mockFunding.getCashInterestResult = .success(
            Self.stub(state: .active, apy: "0.0425", since: "2025-10-01T00:00:00+00:00")
        )

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .active)
        XCTAssertEqual(viewModel.apy, Decimal(string: "0.0425"))
        XCTAssertNotNil(viewModel.sweepEnrolledAt)
        XCTAssertNil(viewModel.error)
    }

    func testLoadSurfacesError() async {
        struct LoadError: LocalizedError {
            var errorDescription: String? { "load failed" }
        }
        mockFunding.getCashInterestResult = .failure(LoadError())

        await viewModel.load()

        XCTAssertEqual(viewModel.error, "load failed")
        XCTAssertEqual(viewModel.state, .unavailable)
    }

    func testConcurrentLoadsCoalesceToSingleServiceCall() async {
        mockFunding.getCashInterestResult = .success(Self.stub(state: .active))
        mockFunding.isGated = true

        let inFlight = Task { await viewModel.load() }
        while !viewModel.isLoading { await Task.yield() }

        await viewModel.load()

        mockFunding.releaseGate()
        await inFlight.value
        XCTAssertEqual(mockFunding.getCashInterestCalls, 1)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - reenroll

    func testReenrollHappyPathTransitionsToPending() async {
        mockFunding.getCashInterestResult = .success(Self.stub(state: .notEnrolled))
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .notEnrolled)

        mockFunding.enrollCashInterestResult = .success(Self.stub(state: .pending))
        await viewModel.reenroll()

        XCTAssertEqual(mockFunding.enrollCashInterestCalls, 1)
        XCTAssertEqual(viewModel.state, .pending)
        XCTAssertFalse(viewModel.isEnrolling)
        XCTAssertNil(viewModel.error)
    }

    func testReenrollErrorRevertsStateAndSurfacesError() async {
        mockFunding.getCashInterestResult = .success(Self.stub(state: .notEnrolled))
        await viewModel.load()

        struct EnrollError: LocalizedError {
            var errorDescription: String? { "enroll failed" }
        }
        mockFunding.enrollCashInterestResult = .failure(EnrollError())
        await viewModel.reenroll()

        XCTAssertEqual(mockFunding.enrollCashInterestCalls, 1)
        XCTAssertEqual(viewModel.state, .notEnrolled)
        XCTAssertEqual(viewModel.error, "enroll failed")
        XCTAssertFalse(viewModel.isEnrolling)
    }

    func testReenrollFlipsToPendingBeforeServiceResolves() async {
        mockFunding.getCashInterestResult = .success(Self.stub(state: .notEnrolled))
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .notEnrolled)

        mockFunding.enrollCashInterestResult = .success(Self.stub(state: .active))
        mockFunding.isGated = true

        let inFlight = Task { await viewModel.reenroll() }
        while !viewModel.isEnrolling { await Task.yield() }

        XCTAssertEqual(viewModel.state, .pending)

        mockFunding.releaseGate()
        await inFlight.value
        XCTAssertEqual(viewModel.state, .active)
        XCTAssertFalse(viewModel.isEnrolling)
    }

    // MARK: - Fixtures

    private static func stub(
        state: EnrollmentState,
        apy: String = "0.0425",
        since: String? = nil
    ) -> CashInterestResponse {
        CashInterestResponse(
            balance: "2412.08",
            apy: apy,
            thisMonthEarned: "6.43",
            daysAccrued: 22,
            lifetimeEarned: "41.87",
            lifetimeSince: since,
            buyingPower: "2412.08",
            pendingDeposits: "0",
            interestPaidOut: "monthly",
            fdicInsuredLimit: "2500000",
            sweepStatus: nil,
            enrollmentState: state
        )
    }
}
