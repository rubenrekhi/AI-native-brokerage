import Foundation
@testable import Sevino

final class MockFundingService: FundingServiceProtocol, @unchecked Sendable {

    // Stubs
    var createLinkTokenResult: Result<String, Error> = .success("link-sandbox-test")
    var linkBankResult: Result<AchRelationshipDTO, Error>?
    var listAchRelationshipsResult: Result<[AchRelationshipDTO], Error> = .success([])

    // Call tracking
    private(set) var createLinkTokenCalls = 0
    private(set) var linkBankCalls: [LinkBankRequest] = []
    private(set) var listAchRelationshipsCalls = 0

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
}
