import XCTest
@testable import Sevino

@MainActor
final class AccountHistoryViewModelTests: XCTestCase {

    private func makeSUT(
        mock: MockFundingService = MockFundingService()
    ) -> (AccountHistoryViewModel, MockFundingService) {
        (AccountHistoryViewModel(fundingService: mock), mock)
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

    // MARK: - load

    func test_load_populatesTransfersSortedNewestFirst() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "old", createdAt: "2026-01-01T10:00:00Z"),
            makeTransfer(id: "new", createdAt: "2026-04-20T10:00:00Z"),
            makeTransfer(id: "mid", createdAt: "2026-02-15T10:00:00Z"),
        ])

        await sut.load()

        XCTAssertEqual(sut.transfers.map(\.id), ["new", "mid", "old"])
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.error)
    }

    func test_load_placesNilDatesAfterDatedEntries() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([
            makeTransfer(id: "nil1", createdAt: nil),
            makeTransfer(id: "dated", createdAt: "2026-04-20T10:00:00Z"),
            makeTransfer(id: "nil2", createdAt: nil),
        ])

        await sut.load()

        XCTAssertEqual(sut.transfers.first?.id, "dated")
        XCTAssertEqual(Set(sut.transfers.suffix(2).map(\.id)), Set(["nil1", "nil2"]))
    }

    func test_load_onFailure_setsLocalizedErrorAndClearsLoading() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)

        await sut.load()

        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)
        XCTAssertFalse(sut.isLoading)
        XCTAssertTrue(sut.transfers.isEmpty)
    }

    func test_load_clearsPriorErrorOnSuccess() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()
        XCTAssertNotNil(sut.error)

        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-04-20T10:00:00Z")])
        await sut.load()

        XCTAssertNil(sut.error)
        XCTAssertEqual(sut.transfers.count, 1)
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

    func test_isShowingError_falseWhenErrorButNoCachedTransfers() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertTrue(sut.transfers.isEmpty)
        XCTAssertFalse(sut.isShowingError)
    }

    func test_isShowingError_trueWhenErrorFollowsSuccessfulLoad() async {
        let (sut, mock) = makeSUT()
        mock.listTransfersResult = .success([makeTransfer(id: "t", createdAt: "2026-04-20T10:00:00Z")])
        await sut.load()
        mock.listTransfersResult = .failure(TestError.boom)
        await sut.load()

        XCTAssertNotNil(sut.error)
        XCTAssertFalse(sut.transfers.isEmpty)
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

    // MARK: - service wiring

    func test_load_invokesListTransfers() async {
        let (sut, mock) = makeSUT()

        await sut.load()
        await sut.load()

        XCTAssertEqual(mock.listTransfersCalls, 2)
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "boom" }
    }
}
