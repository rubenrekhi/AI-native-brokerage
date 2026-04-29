import XCTest
@testable import Sevino

@MainActor
final class FundingViewModelTests: XCTestCase {

    private func makeSUT(
        mock: MockFundingService = MockFundingService()
    ) -> (FundingViewModel, MockFundingService) {
        (FundingViewModel(service: mock), mock)
    }

    private func makeRelationship(
        id: UUID = UUID(),
        status: String = "QUEUED",
        nickname: String? = nil
    ) -> AchRelationshipDTO {
        AchRelationshipDTO(
            id: id,
            alpacaRelationshipId: "rel_\(id.uuidString.prefix(8))",
            institutionName: "First Platypus Bank",
            accountMask: "0000",
            accountType: "CHECKING",
            nickname: nickname,
            status: status
        )
    }

    // MARK: - loadRelationships

    func test_loadRelationships_populatesRelationshipsAndFlipsHasLinkedBank() async {
        let (sut, mock) = makeSUT()
        let rel = makeRelationship()
        mock.listAchRelationshipsResult = .success([rel])

        await sut.loadRelationships()

        XCTAssertEqual(sut.relationships, [rel])
        XCTAssertTrue(sut.hasLinkedBank)
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.displayedError)
    }

    func test_loadRelationships_whenEmpty_hasLinkedBankIsFalse() async {
        let (sut, mock) = makeSUT()
        mock.listAchRelationshipsResult = .success([])

        await sut.loadRelationships()

        XCTAssertTrue(sut.relationships.isEmpty)
        XCTAssertFalse(sut.hasLinkedBank)
    }

    func test_loadRelationships_whenApiFails_storesServerError() async {
        let (sut, mock) = makeSUT()
        let error = APIError(error: "Nope", code: "INTERNAL_ERROR")
        mock.listAchRelationshipsResult = .failure(error)

        await sut.loadRelationships()

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(sut.displayedError, "Nope")
        XCTAssertTrue(sut.relationships.isEmpty)
    }

    // MARK: - Plaid coordinator wiring

    func test_plaidLink_onSuccess_refreshesRelationships() async {
        let (sut, mock) = makeSUT()
        let rel = makeRelationship()
        mock.linkBankResult = .success(rel)
        mock.listAchRelationshipsResult = .success([rel])

        await sut.plaidLink.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertEqual(mock.listAchRelationshipsCalls, 1)
        XCTAssertEqual(sut.relationships, [rel])
        XCTAssertTrue(sut.hasLinkedBank)
    }

    func test_requestBankLink_forwardsToCoordinator() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .success("link-sandbox-abc")

        sut.requestBankLink()
        // Drain the Task scheduled by requestBankLink.
        for _ in 0..<10 where sut.plaidLink.linkToken == nil {
            await Task.yield()
        }

        XCTAssertEqual(sut.plaidLink.linkToken, "link-sandbox-abc")
    }

    // MARK: - displayedError coalescing

    func test_displayedError_prefersPlaidLinkErrorOverRelationshipError() async {
        let (sut, mock) = makeSUT()
        let plaidError = APIError(error: "Plaid says no", code: "INTERNAL_ERROR")
        mock.createLinkTokenResult = .failure(plaidError)
        await sut.plaidLink.startBankLink()
        sut.localError = "Stale relationship-load error"

        XCTAssertEqual(sut.displayedError, "Plaid says no")
    }

    func test_displayedError_whenOnlyRelationshipError_returnsRelationshipError() {
        let (sut, _) = makeSUT()
        sut.localError = "Only local"

        XCTAssertEqual(sut.displayedError, "Only local")
    }

    func test_clearErrors_resetsBothVMAndCoordinatorChannels() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .failure(APIError(error: "p", code: "INTERNAL_ERROR"))
        await sut.plaidLink.startBankLink()
        sut.serverError = APIError(error: "r", code: "INTERNAL_ERROR")
        sut.localError = "rl"

        sut.clearErrors()

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
        XCTAssertNil(sut.plaidLink.serverError)
        XCTAssertNil(sut.plaidLink.localError)
        XCTAssertNil(sut.displayedError)
    }
}
