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
        nickname: String? = nil,
        requiresReauth: Bool = false
    ) -> AchRelationshipDTO {
        AchRelationshipDTO(
            id: id,
            alpacaRelationshipId: "rel_\(id.uuidString.prefix(8))",
            institutionName: "First Platypus Bank",
            accountMask: "0000",
            accountType: "CHECKING",
            nickname: nickname,
            status: status,
            requiresReauth: requiresReauth
        )
    }

    // MARK: - firstRequiresReauth

    func test_firstRequiresReauth_returnsNilWhenNoneNeedReauth() async {
        let (sut, mock) = makeSUT()
        mock.listAchRelationshipsResult = .success([makeRelationship()])
        await sut.loadRelationships()

        XCTAssertNil(sut.firstRequiresReauth)
    }

    func test_firstRequiresReauth_returnsTheFlaggedRelationship() async {
        let (sut, mock) = makeSUT()
        let flagged = makeRelationship(requiresReauth: true)
        mock.listAchRelationshipsResult = .success([
            makeRelationship(),
            flagged,
            makeRelationship(requiresReauth: true),
        ])
        await sut.loadRelationships()

        XCTAssertEqual(sut.firstRequiresReauth?.id, flagged.id)
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

    // MARK: - loadCashInterest

    private func makeCashResponse(
        balance: String = "2412.08",
        apy: String = "0.0425",
        thisMonthEarned: String = "6.43",
        daysAccrued: Int = 22,
        lifetimeEarned: String = "41.87",
        lifetimeSince: String? = "2025-10-01T00:00:00+00:00",
        buyingPower: String = "2412.08",
        pendingDeposits: String = "100.50",
        interestPaidOut: String = "monthly",
        fdicInsuredLimit: String = "2500000",
        sweepStatus: String? = "ACTIVE"
    ) -> CashInterestResponse {
        CashInterestResponse(
            balance: balance,
            apy: apy,
            thisMonthEarned: thisMonthEarned,
            daysAccrued: daysAccrued,
            lifetimeEarned: lifetimeEarned,
            lifetimeSince: lifetimeSince,
            buyingPower: buyingPower,
            pendingDeposits: pendingDeposits,
            interestPaidOut: interestPaidOut,
            fdicInsuredLimit: fdicInsuredLimit,
            sweepStatus: sweepStatus
        )
    }

    func test_loadCashInterest_mapsAllFieldsFromResponse() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse())

        await sut.loadCashInterest()

        XCTAssertEqual(sut.cashBalance, Decimal(string: "2412.08"))
        XCTAssertEqual(sut.cashApy, Decimal(string: "0.0425"))
        XCTAssertEqual(sut.cashThisMonthEarned, Decimal(string: "6.43"))
        XCTAssertEqual(sut.cashDaysAccrued, 22)
        XCTAssertEqual(sut.cashLifetimeEarned, Decimal(string: "41.87"))
        XCTAssertEqual(sut.cashBuyingPower, Decimal(string: "2412.08"))
        XCTAssertEqual(sut.cashPendingDeposits, Decimal(string: "100.50"))
        XCTAssertEqual(sut.cashFdicInsuredLimit, Decimal(string: "2500000"))
        XCTAssertEqual(sut.cashInterestPaidOut, .monthly)

        let expected = DateComponents(
            calendar: Calendar(identifier: .gregorian),
            timeZone: TimeZone(secondsFromGMT: 0),
            year: 2025, month: 10, day: 1
        ).date
        XCTAssertEqual(sut.cashLifetimeSince, expected)
    }

    func test_loadCashInterest_parsesISO8601WithFractionalSeconds() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(
            lifetimeSince: "2025-10-01T00:00:00.123Z"
        ))

        await sut.loadCashInterest()

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        XCTAssertEqual(sut.cashLifetimeSince, formatter.date(from: "2025-10-01T00:00:00.123Z"))
    }

    func test_loadCashInterest_leavesLifetimeSinceNilWhenMissing() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(lifetimeSince: nil))

        await sut.loadCashInterest()

        XCTAssertNil(sut.cashLifetimeSince)
    }

    func test_loadCashInterest_mapsCadenceVariants() async {
        for raw in ["monthly", "quarterly", "annually"] {
            let (sut, mock) = makeSUT()
            mock.getCashInterestResult = .success(makeCashResponse(interestPaidOut: raw))
            await sut.loadCashInterest()
            XCTAssertEqual(sut.cashInterestPaidOut, PaidOutCadence(rawValue: raw))
        }
    }

    func test_loadCashInterest_unknownCadenceFallsBackToMonthly() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(interestPaidOut: "weekly"))

        await sut.loadCashInterest()

        XCTAssertEqual(sut.cashInterestPaidOut, .monthly)
    }

    func test_loadCashInterest_malformedDecimalsFallToZero() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(
            balance: "not-a-number",
            apy: "oops",
            thisMonthEarned: "",
            lifetimeEarned: "??",
            buyingPower: "x",
            pendingDeposits: "y"
        ))

        await sut.loadCashInterest()

        XCTAssertEqual(sut.cashBalance, 0)
        XCTAssertEqual(sut.cashApy, 0)
        XCTAssertEqual(sut.cashThisMonthEarned, 0)
        XCTAssertEqual(sut.cashLifetimeEarned, 0)
        XCTAssertEqual(sut.cashBuyingPower, 0)
        XCTAssertEqual(sut.cashPendingDeposits, 0)
    }

    func test_loadCashInterest_malformedFdicLimitFallsBackTo2_5M() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(fdicInsuredLimit: "garbage"))

        await sut.loadCashInterest()

        XCTAssertEqual(sut.cashFdicInsuredLimit, 2_500_000)
    }

    func test_loadCashInterest_zerosForInactiveSweep() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse(
            balance: "0",
            apy: "0",
            thisMonthEarned: "0",
            daysAccrued: 0,
            lifetimeEarned: "0",
            lifetimeSince: nil,
            buyingPower: "0",
            pendingDeposits: "0",
            sweepStatus: "INACTIVE"
        ))

        await sut.loadCashInterest()

        XCTAssertEqual(sut.cashBalance, 0)
        XCTAssertEqual(sut.cashApy, 0)
        XCTAssertEqual(sut.cashThisMonthEarned, 0)
        XCTAssertEqual(sut.cashDaysAccrued, 0)
        XCTAssertEqual(sut.cashLifetimeEarned, 0)
        XCTAssertNil(sut.serverError)
        XCTAssertNil(sut.localError)
    }

    func test_loadCashInterest_onAPIError_setsServerError() async {
        let (sut, mock) = makeSUT()
        let apiError = APIError(error: "service down", code: "ALPACA_UNAVAILABLE")
        mock.getCashInterestResult = .failure(apiError)

        await sut.loadCashInterest()

        XCTAssertEqual(sut.serverError?.code, "ALPACA_UNAVAILABLE")
        XCTAssertNil(sut.localError)
    }

    func test_loadCashInterest_onGenericError_setsLocalError() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .failure(URLError(.notConnectedToInternet))

        await sut.loadCashInterest()

        XCTAssertEqual(sut.localError, L10n.Home.fundingGenericError)
        XCTAssertNil(sut.serverError)
    }

    func test_loadCashInterest_isIdempotentAndKeepsLatestState() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse())

        await sut.loadCashInterest()
        await sut.loadCashInterest()

        XCTAssertEqual(mock.getCashInterestCalls, 2)
        XCTAssertEqual(sut.cashBalance, Decimal(string: "2412.08"))
    }

    func test_loadCashInterest_doesNotClobberPriorRelationshipError() async {
        let (sut, mock) = makeSUT()
        let priorError = APIError(error: "rel failed", code: "INTERNAL_ERROR")
        sut.serverError = priorError
        mock.getCashInterestResult = .success(makeCashResponse())

        await sut.loadCashInterest()

        XCTAssertEqual(sut.serverError, priorError)
    }

    func test_loadCashInterest_togglesIsLoading() async {
        let (sut, mock) = makeSUT()
        mock.getCashInterestResult = .success(makeCashResponse())

        await sut.loadCashInterest()

        XCTAssertFalse(sut.isLoading)
    }

    // MARK: - CashInterestResponse decoding

    func test_cashInterestResponse_decodesFromSnakeCaseJSON() throws {
        let json = """
        {
          "balance": "2412.08",
          "apy": "0.0425",
          "this_month_earned": "6.43",
          "days_accrued": 22,
          "lifetime_earned": "41.87",
          "lifetime_since": "2025-10-01T00:00:00+00:00",
          "buying_power": "2412.08",
          "pending_deposits": "100.50",
          "interest_paid_out": "monthly",
          "fdic_insured_limit": "2500000",
          "sweep_status": "ACTIVE"
        }
        """.data(using: .utf8)!

        let dto = try JSONDecoder.sevino().decode(CashInterestResponse.self, from: json)

        XCTAssertEqual(dto.balance, "2412.08")
        XCTAssertEqual(dto.apy, "0.0425")
        XCTAssertEqual(dto.thisMonthEarned, "6.43")
        XCTAssertEqual(dto.daysAccrued, 22)
        XCTAssertEqual(dto.lifetimeEarned, "41.87")
        XCTAssertEqual(dto.lifetimeSince, "2025-10-01T00:00:00+00:00")
        XCTAssertEqual(dto.buyingPower, "2412.08")
        XCTAssertEqual(dto.pendingDeposits, "100.50")
        XCTAssertEqual(dto.interestPaidOut, "monthly")
        XCTAssertEqual(dto.fdicInsuredLimit, "2500000")
        XCTAssertEqual(dto.sweepStatus, "ACTIVE")
    }

    func test_cashInterestResponse_decodesWithNullableOptionals() throws {
        let json = """
        {
          "balance": "0",
          "apy": "0",
          "this_month_earned": "0",
          "days_accrued": 0,
          "lifetime_earned": "0",
          "lifetime_since": null,
          "buying_power": "0",
          "pending_deposits": "0",
          "interest_paid_out": "monthly",
          "fdic_insured_limit": "2500000",
          "sweep_status": null
        }
        """.data(using: .utf8)!

        let dto = try JSONDecoder.sevino().decode(CashInterestResponse.self, from: json)

        XCTAssertNil(dto.lifetimeSince)
        XCTAssertNil(dto.sweepStatus)
    }
}
