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

    // MARK: - startBankLink

    func test_startBankLink_setsTokenAndShowsSheet() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .success("link-sandbox-abc")

        await sut.startBankLink()

        XCTAssertEqual(sut.linkToken, "link-sandbox-abc")
        XCTAssertTrue(sut.isShowingPlaidLink)
        XCTAssertNil(sut.displayedError)
        XCTAssertEqual(mock.createLinkTokenCalls, 1)
    }

    func test_startBankLink_whenApiFails_storesServerErrorAndDoesNotShowSheet() async {
        let (sut, mock) = makeSUT()
        let error = APIError(error: "Account not active", code: "ACCOUNT_NOT_ACTIVE")
        mock.createLinkTokenResult = .failure(error)

        await sut.startBankLink()

        XCTAssertEqual(sut.serverError, error)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
    }

    func test_startBankLink_whenNonAPIErrorThrown_storesLocalErrorFallback() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .failure(URLError(.notConnectedToInternet))

        await sut.startBankLink()

        XCTAssertNil(sut.serverError)
        XCTAssertEqual(sut.localError, L10n.Home.fundingGenericError)
        XCTAssertEqual(sut.displayedError, L10n.Home.fundingGenericError)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_startBankLink_clearsPreExistingErrors() async {
        let (sut, mock) = makeSUT()
        sut.serverError = APIError(error: "old", code: "INTERNAL_ERROR")
        sut.localError = "old-local"
        mock.createLinkTokenResult = .success("link-sandbox-abc")

        await sut.startBankLink()

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
    }

    // MARK: - onPlaidSuccess

    func test_onPlaidSuccess_happyPath_refreshesRelationshipsAndDismissesSheet() async {
        let (sut, mock) = makeSUT()
        let rel = makeRelationship()
        mock.linkBankResult = .success(rel)
        mock.listAchRelationshipsResult = .success([rel])
        sut.linkToken = "link-sandbox-abc"
        sut.isShowingPlaidLink = true

        await sut.onPlaidSuccess(
            publicToken: "public-sandbox-xyz",
            accountId: "acct_123",
            institutionName: "First Platypus Bank",
            accountMask: "0000",
            accountName: "Plaid Checking"
        )

        XCTAssertEqual(mock.linkBankCalls.count, 1)
        XCTAssertEqual(mock.linkBankCalls.first?.publicToken, "public-sandbox-xyz")
        XCTAssertEqual(mock.linkBankCalls.first?.accountId, "acct_123")
        XCTAssertNil(mock.linkBankCalls.first?.nickname)
        XCTAssertEqual(mock.listAchRelationshipsCalls, 1)
        XCTAssertEqual(sut.relationships, [rel])
        XCTAssertTrue(sut.hasLinkedBank)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
        XCTAssertNil(sut.displayedError)
    }

    func test_onPlaidSuccess_withBankAlreadyLinked_storesServerErrorAndStillRefreshes() async {
        let (sut, mock) = makeSUT()
        let error = APIError(error: "Already linked", code: "BANK_ALREADY_LINKED")
        mock.linkBankResult = .failure(error)
        let existing = makeRelationship()
        mock.listAchRelationshipsResult = .success([existing])
        sut.isShowingPlaidLink = true

        await sut.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(mock.listAchRelationshipsCalls, 1,
                       "BANK_ALREADY_LINKED should still refresh relationships")
        XCTAssertEqual(sut.relationships, [existing])
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_onPlaidSuccess_withAccountNotActive_storesServerErrorAndDismisses() async {
        let (sut, mock) = makeSUT()
        let error = APIError(error: "Account not active", code: "ACCOUNT_NOT_ACTIVE")
        mock.linkBankResult = .failure(error)
        sut.isShowingPlaidLink = true

        await sut.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(mock.listAchRelationshipsCalls, 0,
                       "non-BANK_ALREADY_LINKED errors should not trigger refresh")
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_onPlaidSuccess_whenNonAPIErrorThrown_storesLocalErrorFallback() async {
        let (sut, mock) = makeSUT()
        mock.linkBankResult = .failure(URLError(.timedOut))
        sut.isShowingPlaidLink = true

        await sut.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertNil(sut.serverError)
        XCTAssertEqual(sut.localError, L10n.Home.fundingGenericError)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    // MARK: - onPlaidExit

    func test_onPlaidExit_withNilError_isSilent() {
        let (sut, _) = makeSUT()
        sut.isShowingPlaidLink = true
        sut.linkToken = "link-sandbox-abc"

        sut.onPlaidExit(error: nil)

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
        XCTAssertNil(sut.displayedError)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
    }

    func test_onPlaidExit_withNonNilError_storesLocalErrorCopy() {
        let (sut, _) = makeSUT()
        sut.isShowingPlaidLink = true

        sut.onPlaidExit(error: URLError(.notConnectedToInternet))

        XCTAssertEqual(sut.localError, L10n.Home.fundingPlaidConnectionError)
        XCTAssertNil(sut.serverError)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    // MARK: - displayedError coalescing

    func test_displayedError_prefersServerErrorOverLocalError() {
        let (sut, _) = makeSUT()
        sut.serverError = APIError(error: "Server says no", code: "INTERNAL_ERROR")
        sut.localError = "Local fallback"

        XCTAssertEqual(sut.displayedError, "Server says no")
    }

    func test_displayedError_whenOnlyLocal_returnsLocal() {
        let (sut, _) = makeSUT()
        sut.localError = "Only local"

        XCTAssertEqual(sut.displayedError, "Only local")
    }

    func test_clearErrors_resetsBothSources() {
        let (sut, _) = makeSUT()
        sut.serverError = APIError(error: "e", code: "INTERNAL_ERROR")
        sut.localError = "l"

        sut.clearErrors()

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
        XCTAssertNil(sut.displayedError)
    }
}
