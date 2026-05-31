import XCTest
@testable import Sevino

@MainActor
final class AccountHistoryViewModelTests: XCTestCase {

    /// Fixed reference point so timeframe assertions stay deterministic.
    private let now = ISO8601DateFormatter().date(from: "2026-05-31T00:00:00Z")!

    private func makeSUT(
        mock: MockFundingService = MockFundingService()
    ) -> (AccountHistoryViewModel, MockFundingService) {
        let sut = AccountHistoryViewModel(fundingService: mock, now: { self.now })
        return (sut, mock)
    }

    private func makeTransfer(
        id: String,
        createdAt: String?,
        direction: String = "INCOMING",
        status: String = "COMPLETE"
    ) -> TransferResponse {
        TransferResponse(
            id: id,
            status: status,
            amount: "100.00",
            direction: direction,
            createdAt: createdAt,
            reason: nil,
            bank: nil
        )
    }

    private func makeDividend(
        id: String,
        createdAt: String?,
        symbol: String = "AAPL",
        status: String = "executed"
    ) -> DividendResponse {
        DividendResponse(
            id: id,
            symbol: symbol,
            netAmount: "10.00",
            status: status,
            createdAt: createdAt
        )
    }

    private func ids(_ items: [AccountHistoryItem]) -> [String] {
        items.map(\.id)
    }

    // MARK: - load — merge & sort

    func test_load_mergesTransfersAndDividendsSortedNewestFirst() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "t-old", createdAt: "2026-01-01T10:00:00Z"),
            makeTransfer(id: "t-mid", createdAt: "2026-03-15T10:00:00Z"),
        ])
        mock.listDividendsResult = .success([
            makeDividend(id: "d-new", createdAt: "2026-05-01T10:00:00Z"),
            makeDividend(id: "d-mid", createdAt: "2026-02-15T10:00:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(ids(sut.items), ["d-d-new", "t-t-mid", "d-d-mid", "t-t-old"])
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.error)
    }

    func test_load_placesNilDatesAfterDatedEntriesAcrossBothSources() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "t-nil", createdAt: nil),
            makeTransfer(id: "t-dated", createdAt: "2026-04-20T10:00:00Z"),
        ])
        mock.listDividendsResult = .success([
            makeDividend(id: "d-nil", createdAt: nil),
            makeDividend(id: "d-dated", createdAt: "2026-05-20T10:00:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(sut.items.prefix(2).map(\.id), ["d-d-dated", "t-t-dated"])
        XCTAssertEqual(Set(sut.items.suffix(2).map(\.id)), Set(["t-t-nil", "d-d-nil"]))
    }

    func test_load_invokesBothEndpointsWithDefaultPagination() async {
        let (sut, mock) = makeSUT()

        await sut.load()

        XCTAssertEqual(mock.listTransfersCalls, 1)
        XCTAssertEqual(mock.listDividendsCalls.count, 1)
        XCTAssertEqual(mock.listDividendsCalls.first?.limit, 50)
        XCTAssertEqual(mock.listDividendsCalls.first?.offset, 0)
    }

    // MARK: - load — failure surfaces

    func test_load_whenTransfersFails_surfacesErrorAndLeavesItemsEmpty() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        mock.listDividendsResult = .success([makeDividend(id: "d", createdAt: "2026-05-01T10:00:00Z")])

        await sut.load()

        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)
        XCTAssertTrue(sut.items.isEmpty)
        XCTAssertFalse(sut.isLoading)
    }

    func test_load_whenDividendsFails_surfacesErrorAndLeavesItemsEmpty() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-05-01T10:00:00Z")])
        mock.listDividendsResult = .failure(TestError.boom)

        await sut.load()

        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)
        XCTAssertTrue(sut.items.isEmpty)
    }

    func test_load_clearsPriorErrorOnSuccess() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertNotNil(sut.error)

        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-04-20T10:00:00Z")])
        await sut.load()

        XCTAssertNil(sut.error)
        XCTAssertEqual(sut.items.count, 1)
    }

    // MARK: - typeFilter

    func test_typeFilter_allReturnsEverythingInSortedOrder() async {
        let (sut, _) = primedSUT()
        await sut.load()

        sut.typeFilter = .all

        XCTAssertEqual(ids(sut.visibleItems), ["t-t-deposit", "d-d-aapl", "t-t-withdraw", "d-d-msft"])
    }

    func test_typeFilter_depositsKeepsOnlyIncomingTransfers() async {
        let (sut, _) = primedSUT()
        await sut.load()

        sut.typeFilter = .deposits

        XCTAssertEqual(ids(sut.visibleItems), ["t-t-deposit"])
    }

    func test_typeFilter_withdrawalsKeepsOnlyOutgoingTransfers() async {
        let (sut, _) = primedSUT()
        await sut.load()

        sut.typeFilter = .withdrawals

        XCTAssertEqual(ids(sut.visibleItems), ["t-t-withdraw"])
    }

    func test_typeFilter_dividendsKeepsOnlyDividends() async {
        let (sut, _) = primedSUT()
        await sut.load()

        sut.typeFilter = .dividends

        XCTAssertEqual(ids(sut.visibleItems), ["d-d-aapl", "d-d-msft"])
    }

    func test_typeFilter_switchingDoesNotRefetch() async {
        let (sut, mock) = primedSUT()
        await sut.load()
        let transfersCalls = mock.listTransfersCalls
        let dividendsCalls = mock.listDividendsCalls.count

        sut.typeFilter = .deposits
        sut.typeFilter = .dividends
        sut.typeFilter = .all

        XCTAssertEqual(mock.listTransfersCalls, transfersCalls)
        XCTAssertEqual(mock.listDividendsCalls.count, dividendsCalls)
    }

    // MARK: - timeframeFilter

    func test_timeframeFilter_last7DaysKeepsOnlyRecent() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "fresh", createdAt: "2026-05-28T10:00:00Z"),
            makeTransfer(id: "stale", createdAt: "2026-04-20T10:00:00Z"),
        ])
        mock.listDividendsResult = .success([])
        await sut.load()

        sut.timeframeFilter = .last7Days

        XCTAssertEqual(ids(sut.visibleItems), ["t-fresh"])
    }

    func test_timeframeFilter_last30DaysWidensWindow() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "may-28", createdAt: "2026-05-28T10:00:00Z"),
            makeTransfer(id: "may-10", createdAt: "2026-05-10T10:00:00Z"),
            makeTransfer(id: "apr-20", createdAt: "2026-04-20T10:00:00Z"),
        ])
        mock.listDividendsResult = .success([])
        await sut.load()

        sut.timeframeFilter = .last30Days

        XCTAssertEqual(ids(sut.visibleItems), ["t-may-28", "t-may-10"])
    }

    func test_timeframeFilter_nilDatesAreExcludedWhenWindowSet() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "dated", createdAt: "2026-05-28T10:00:00Z"),
            makeTransfer(id: "nil-date", createdAt: nil),
        ])
        mock.listDividendsResult = .success([])
        await sut.load()

        sut.timeframeFilter = .last7Days

        XCTAssertEqual(ids(sut.visibleItems), ["t-dated"])
    }

    func test_timeframeFilter_last90DaysIncludesEntriesUpTo90DaysOld() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "in-window", createdAt: "2026-03-15T10:00:00Z"),
            makeTransfer(id: "out-of-window", createdAt: "2026-01-15T10:00:00Z"),
        ])
        mock.listDividendsResult = .success([])
        await sut.load()

        sut.timeframeFilter = .last90Days

        XCTAssertEqual(ids(sut.visibleItems), ["t-in-window"])
    }

    func test_timeframeFilter_allKeepsNilDates() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "dated", createdAt: "2026-05-28T10:00:00Z"),
            makeTransfer(id: "nil-date", createdAt: nil),
        ])
        mock.listDividendsResult = .success([])
        await sut.load()

        sut.timeframeFilter = .all

        XCTAssertEqual(Set(ids(sut.visibleItems)), Set(["t-dated", "t-nil-date"]))
    }

    // MARK: - combined filters

    func test_typeAndTimeframe_compose() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "deposit-recent", createdAt: "2026-05-28T10:00:00Z", direction: "INCOMING"),
            makeTransfer(id: "deposit-old", createdAt: "2026-01-01T10:00:00Z", direction: "INCOMING"),
            makeTransfer(id: "withdraw-recent", createdAt: "2026-05-29T10:00:00Z", direction: "OUTGOING"),
        ])
        mock.listDividendsResult = .success([
            makeDividend(id: "div-recent", createdAt: "2026-05-30T10:00:00Z"),
        ])
        await sut.load()

        sut.typeFilter = .deposits
        sut.timeframeFilter = .last7Days

        XCTAssertEqual(ids(sut.visibleItems), ["t-deposit-recent"])
    }

    func test_dividendsFilter_withTimeframe_composes() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "deposit-in-window", createdAt: "2026-05-15T10:00:00Z", direction: "INCOMING"),
        ])
        mock.listDividendsResult = .success([
            makeDividend(id: "div-in-window", createdAt: "2026-05-10T10:00:00Z"),
            makeDividend(id: "div-out-of-window", createdAt: "2026-03-01T10:00:00Z"),
        ])
        await sut.load()

        sut.typeFilter = .dividends
        sut.timeframeFilter = .last30Days

        XCTAssertEqual(ids(sut.visibleItems), ["d-div-in-window"])
    }

    // MARK: - clearError

    func test_clearError_resetsError() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertNotNil(sut.error)

        sut.clearError()

        XCTAssertNil(sut.error)
    }

    // MARK: - isShowingError

    func test_isShowingError_falseWhenNoError() {
        let (sut, _) = makeSUT()
        XCTAssertFalse(sut.isShowingError)
    }

    func test_isShowingError_falseWhenErrorButNoCachedItems() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertTrue(sut.items.isEmpty)
        XCTAssertFalse(sut.isShowingError)
    }

    func test_isShowingError_trueWhenErrorFollowsSuccessfulLoad() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-04-20T10:00:00Z")])
        await sut.load()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertFalse(sut.items.isEmpty)
        XCTAssertTrue(sut.isShowingError)
    }

    func test_isShowingError_settingFalseClearsError() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-04-20T10:00:00Z")])
        await sut.load()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertTrue(sut.isShowingError)

        sut.isShowingError = false

        XCTAssertNil(sut.error)
        XCTAssertFalse(sut.isShowingError)
    }

    // MARK: - helpers

    /// Loads one deposit, one withdrawal, two dividends spanning April–May 2026.
    /// Sorted desc by date once `load()` runs:
    /// t-deposit (May 20), d-aapl (May 1), t-withdraw (Apr 15), d-msft (Apr 1).
    private func primedSUT() -> (AccountHistoryViewModel, MockFundingService) {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "t-deposit", createdAt: "2026-05-20T10:00:00Z", direction: "INCOMING"),
            makeTransfer(id: "t-withdraw", createdAt: "2026-04-15T10:00:00Z", direction: "OUTGOING"),
        ])
        mock.listDividendsResult = .success([
            makeDividend(id: "d-aapl", createdAt: "2026-05-01T10:00:00Z", symbol: "AAPL"),
            makeDividend(id: "d-msft", createdAt: "2026-04-01T10:00:00Z", symbol: "MSFT"),
        ])
        return (sut, mock)
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "boom" }
    }
}
