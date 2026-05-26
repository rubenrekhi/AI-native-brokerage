import XCTest
@testable import Sevino

@MainActor
final class PlaidLinkCoordinatorTests: XCTestCase {

    private func makeSUT(
        onLinked: @escaping () async -> Void = {}
    ) -> (PlaidLinkCoordinator, MockFundingService) {
        let mock = MockFundingService()
        let sut = PlaidLinkCoordinator(service: mock)
        sut.onLinked = onLinked
        return (sut, mock)
    }

    private func makeRelationship() -> AchRelationshipDTO {
        AchRelationshipDTO(
            id: UUID(),
            alpacaRelationshipId: "rel_abc",
            institutionName: "First Platypus Bank",
            accountMask: "0000",
            accountType: "CHECKING",
            nickname: nil,
            status: "QUEUED",
            requiresReauth: false
        )
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
        // Seed coordinator errors via a prior failing call.
        mock.createLinkTokenResult = .failure(APIError(error: "old", code: "INTERNAL_ERROR"))
        await sut.startBankLink()
        XCTAssertNotNil(sut.serverError)

        mock.createLinkTokenResult = .success("link-sandbox-abc")
        await sut.startBankLink()

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
    }

    // MARK: - onPlaidSuccess

    func test_onPlaidSuccess_happyPath_invokesOnLinkedAndDismissesSheet() async {
        var linkedCalls = 0
        let (sut, mock) = makeSUT(onLinked: { linkedCalls += 1 })
        let rel = makeRelationship()
        mock.linkBankResult = .success(rel)
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        await sut.startBankLink()  // arrange linkToken + isShowingPlaidLink via public API
        XCTAssertTrue(sut.isShowingPlaidLink)

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
        XCTAssertEqual(linkedCalls, 1)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
        XCTAssertNil(sut.displayedError)
    }

    func test_onPlaidSuccess_withBankAlreadyLinked_storesServerErrorAndStillCallsOnLinked() async {
        var linkedCalls = 0
        let (sut, mock) = makeSUT(onLinked: { linkedCalls += 1 })
        let error = APIError(error: "Already linked", code: "BANK_ALREADY_LINKED")
        mock.linkBankResult = .failure(error)

        await sut.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(linkedCalls, 1, "BANK_ALREADY_LINKED should still trigger onLinked")
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_onPlaidSuccess_withAccountNotActive_storesServerErrorAndSkipsOnLinked() async {
        var linkedCalls = 0
        let (sut, mock) = makeSUT(onLinked: { linkedCalls += 1 })
        let error = APIError(error: "Account not active", code: "ACCOUNT_NOT_ACTIVE")
        mock.linkBankResult = .failure(error)

        await sut.onPlaidSuccess(
            publicToken: "pt",
            accountId: "acct",
            institutionName: nil,
            accountMask: nil,
            accountName: nil
        )

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(linkedCalls, 0,
                       "non-BANK_ALREADY_LINKED errors should not trigger onLinked")
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_onPlaidSuccess_whenNonAPIErrorThrown_storesLocalErrorFallback() async {
        let (sut, mock) = makeSUT()
        mock.linkBankResult = .failure(URLError(.timedOut))

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

    func test_onPlaidExit_withNilError_isSilent() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        await sut.startBankLink()

        sut.onPlaidExit(error: nil)

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
        XCTAssertNil(sut.displayedError)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
    }

    func test_onPlaidExit_withNonNilError_storesLocalErrorCopy() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        await sut.startBankLink()

        sut.onPlaidExit(error: URLError(.notConnectedToInternet))

        XCTAssertEqual(sut.localError, L10n.Home.fundingPlaidConnectionError)
        XCTAssertNil(sut.serverError)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    // MARK: - displayedError + showError binding

    func test_displayedError_prefersServerErrorOverLocalError() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .failure(APIError(error: "Server says no", code: "INTERNAL_ERROR"))
        await sut.startBankLink()
        sut.onPlaidExit(error: URLError(.timedOut))  // sets localError too

        XCTAssertEqual(sut.displayedError, "Server says no")
    }

    func test_showError_dismissalClearsErrors() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .failure(APIError(error: "boom", code: "INTERNAL_ERROR"))
        await sut.startBankLink()
        XCTAssertTrue(sut.showError)

        sut.showError = false

        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
        XCTAssertFalse(sut.showError)
    }

    func test_showPlaidLink_dismissalClearsLinkToken() async {
        let (sut, mock) = makeSUT()
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        await sut.startBankLink()
        XCTAssertNotNil(sut.linkToken)

        sut.showPlaidLink = false

        XCTAssertNil(sut.linkToken)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    // MARK: - beginReauth

    func test_beginReauth_setsTokenAndShowsSheet() async {
        let (sut, mock) = makeSUT()
        mock.createReauthLinkTokenResult = .success("link-update-sandbox")
        let relId = UUID()

        await sut.beginReauth(relationshipId: relId)

        XCTAssertEqual(sut.linkToken, "link-update-sandbox")
        XCTAssertTrue(sut.isShowingPlaidLink)
        XCTAssertEqual(mock.createReauthLinkTokenCalls, [relId])
    }

    func test_beginReauth_whenApiFails_storesServerErrorAndDoesNotShowSheet() async {
        let (sut, mock) = makeSUT()
        let error = APIError(error: "Cannot reauth", code: "NOT_FOUND")
        mock.createReauthLinkTokenResult = .failure(error)

        await sut.beginReauth(relationshipId: UUID())

        XCTAssertEqual(sut.serverError, error)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
    }

    func test_beginReauth_whenNonAPIErrorThrown_storesLocalErrorFallback() async {
        let (sut, mock) = makeSUT()
        mock.createReauthLinkTokenResult = .failure(URLError(.notConnectedToInternet))

        await sut.beginReauth(relationshipId: UUID())

        XCTAssertEqual(sut.localError, L10n.Home.fundingGenericError)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    // MARK: - onPlaidSuccess routing through pendingIntent

    func test_onPlaidSuccess_inReauthMode_callsCompleteReauthNotLinkBank() async {
        var linkedCalls = 0
        let (sut, mock) = makeSUT(onLinked: { linkedCalls += 1 })
        let relId = UUID()
        mock.createReauthLinkTokenResult = .success("link-update-sandbox")
        await sut.beginReauth(relationshipId: relId)

        await sut.onPlaidSuccess(
            publicToken: "public-from-update-mode",
            accountId: "acct-ignored",
            institutionName: "Chase",
            accountMask: "1234",
            accountName: "Chase Checking"
        )

        XCTAssertEqual(mock.completeReauthCalls, [relId])
        XCTAssertTrue(
            mock.linkBankCalls.isEmpty,
            "linkBank must not be called after a re-auth — access_token unchanged"
        )
        XCTAssertEqual(linkedCalls, 1)
        XCTAssertFalse(sut.isShowingPlaidLink)
        XCTAssertNil(sut.linkToken)
    }

    func test_onPlaidSuccess_inReauthMode_apiErrorStoresServerError() async {
        var linkedCalls = 0
        let (sut, mock) = makeSUT(onLinked: { linkedCalls += 1 })
        let error = APIError(error: "Bad relationship", code: "NOT_FOUND")
        mock.createReauthLinkTokenResult = .success("link-update-sandbox")
        mock.completeReauthResult = .failure(error)
        await sut.beginReauth(relationshipId: UUID())

        await sut.onPlaidSuccess(
            publicToken: "pt", accountId: "acct",
            institutionName: nil, accountMask: nil, accountName: nil
        )

        XCTAssertEqual(sut.serverError, error)
        XCTAssertEqual(linkedCalls, 0)
        XCTAssertFalse(sut.isShowingPlaidLink)
    }

    func test_onPlaidSuccess_resetsPendingIntentSoNextLinkIsInitial() async {
        let (sut, mock) = makeSUT()
        let rel = makeRelationship()
        mock.createReauthLinkTokenResult = .success("link-update-sandbox")
        mock.linkBankResult = .success(rel)
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        // First trip: re-auth flow.
        await sut.beginReauth(relationshipId: UUID())
        await sut.onPlaidSuccess(
            publicToken: "pt-1", accountId: "acct-1",
            institutionName: nil, accountMask: nil, accountName: nil
        )

        // Second trip: initial link — must route through linkBank, not completeReauth.
        await sut.startBankLink()
        await sut.onPlaidSuccess(
            publicToken: "pt-2", accountId: "acct-2",
            institutionName: nil, accountMask: nil, accountName: nil
        )

        XCTAssertEqual(mock.linkBankCalls.count, 1, "second trip should hit linkBank")
        XCTAssertEqual(mock.completeReauthCalls.count, 1, "completeReauth only ran on the first trip")
    }

    func test_onPlaidExit_resetsPendingIntentSoNextLinkIsInitial() async {
        let (sut, mock) = makeSUT()
        let rel = makeRelationship()
        mock.createReauthLinkTokenResult = .success("link-update-sandbox")
        mock.createLinkTokenResult = .success("link-sandbox-abc")
        mock.linkBankResult = .success(rel)
        await sut.beginReauth(relationshipId: UUID())

        sut.onPlaidExit(error: URLError(.cancelled))

        await sut.startBankLink()
        await sut.onPlaidSuccess(
            publicToken: "pt", accountId: "acct",
            institutionName: nil, accountMask: nil, accountName: nil
        )

        XCTAssertEqual(mock.linkBankCalls.count, 1)
        XCTAssertTrue(mock.completeReauthCalls.isEmpty)
    }
}
