import Foundation
@testable import Sevino

final class MockFundingService: FundingServiceProtocol, @unchecked Sendable {

    // Stubs
    var createLinkTokenResult: Result<String, Error> = .success("link-sandbox-test")
    var linkBankResult: Result<AchRelationshipDTO, Error>?
    var listAchRelationshipsResult: Result<[AchRelationshipDTO], Error> = .success([])
    var deleteAchRelationshipResult: Result<Void, Error> = .success(())
    var createReauthLinkTokenResult: Result<String, Error> = .success("link-update-sandbox")
    var completeReauthResult: Result<Void, Error> = .success(())
    var createTransferResult: Result<TransferResponse, Error>?
    var listTransfersResult: Result<[TransferResponse], Error> = .success([])
    var listDividendsResult: Result<[DividendResponse], Error> = .success([])
    var getCashInterestResult: Result<CashInterestResponse, Error> = .success(
        CashInterestResponse(
            balance: "0",
            apy: "0",
            thisMonthEarned: "0",
            daysAccrued: 0,
            lifetimeEarned: "0",
            lifetimeSince: nil,
            buyingPower: "0",
            pendingDeposits: "0",
            interestPaidOut: "monthly",
            fdicInsuredLimit: "2500000",
            sweepStatus: nil,
            enrollmentState: .active
        )
    )

    // Call tracking
    private(set) var createLinkTokenCalls = 0
    private(set) var linkBankCalls: [LinkBankRequest] = []
    private(set) var listAchRelationshipsCalls = 0
    private(set) var deleteAchRelationshipCalls: [UUID] = []
    private(set) var createReauthLinkTokenCalls: [UUID] = []
    private(set) var completeReauthCalls: [UUID] = []
    private(set) var createTransferCalls: [(relationshipId: String, amount: Decimal, direction: TransferDirection)] = []
    private(set) var listTransfersCalls = 0
    private(set) var listDividendsCalls: [(limit: Int, offset: Int)] = []
    private(set) var getCashInterestCalls = 0

    func createLinkToken() async throws -> String {
        createLinkTokenCalls += 1
        return try createLinkTokenResult.get()
    }

    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO {
        linkBankCalls.append(request)
        guard let result = linkBankResult else {
            fatalError("linkBank called but no result stubbed")
        }
        return try result.get()
    }

    func listAchRelationships() async throws -> [AchRelationshipDTO] {
        listAchRelationshipsCalls += 1
        return try listAchRelationshipsResult.get()
    }

    func deleteAchRelationship(id: UUID) async throws {
        deleteAchRelationshipCalls.append(id)
        try deleteAchRelationshipResult.get()
    }

    func createReauthLinkToken(relationshipId: UUID) async throws -> String {
        createReauthLinkTokenCalls.append(relationshipId)
        return try createReauthLinkTokenResult.get()
    }

    func completeReauth(relationshipId: UUID) async throws {
        completeReauthCalls.append(relationshipId)
        try completeReauthResult.get()
    }

    func createTransfer(
        relationshipId: String,
        amount: Decimal,
        direction: TransferDirection
    ) async throws -> TransferResponse {
        createTransferCalls.append((relationshipId, amount, direction))
        guard let result = createTransferResult else {
            fatalError("createTransfer called but no result stubbed")
        }
        return try result.get()
    }

    func listTransfers() async throws -> [TransferResponse] {
        listTransfersCalls += 1
        return try listTransfersResult.get()
    }

    func listDividends(limit: Int, offset: Int) async throws -> [DividendResponse] {
        listDividendsCalls.append((limit, offset))
        return try listDividendsResult.get()
    }

    func getCashInterest() async throws -> CashInterestResponse {
        getCashInterestCalls += 1
        return try getCashInterestResult.get()
    }
}
