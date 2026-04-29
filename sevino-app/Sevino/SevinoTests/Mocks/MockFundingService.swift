import Foundation
@testable import Sevino

final class MockFundingService: FundingServiceProtocol, @unchecked Sendable {

    // Stubs
    var createLinkTokenResult: Result<String, Error> = .success("link-sandbox-test")
    var linkBankResult: Result<AchRelationshipDTO, Error>?
    var listAchRelationshipsResult: Result<[AchRelationshipDTO], Error> = .success([])
    var deleteAchRelationshipResult: Result<Void, Error> = .success(())
    var createTransferResult: Result<TransferResponse, Error>?
    var listTransfersResult: Result<[TransferResponse], Error> = .success([])

    // Call tracking
    private(set) var createLinkTokenCalls = 0
    private(set) var linkBankCalls: [LinkBankRequest] = []
    private(set) var listAchRelationshipsCalls = 0
    private(set) var deleteAchRelationshipCalls: [UUID] = []
    private(set) var createTransferCalls: [(relationshipId: String, amount: Decimal, direction: TransferDirection)] = []
    private(set) var listTransfersCalls = 0

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
}
