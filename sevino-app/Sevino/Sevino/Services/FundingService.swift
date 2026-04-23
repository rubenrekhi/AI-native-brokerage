import Foundation

/// Protocol for funding backend communication — enables mocking in tests.
protocol FundingServiceProtocol {
    func createLinkToken() async throws -> String
    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO
    func listAchRelationships() async throws -> [AchRelationshipDTO]
}

/// Handles backend communication for the Plaid + ACH funding flows.
final class FundingService: FundingServiceProtocol {
    static let shared = FundingService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func createLinkToken() async throws -> String {
        let response: LinkTokenResponse = try await api.post(
            "/v1/funding/link-token",
            body: EmptyBody()
        )
        return response.linkToken
    }

    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO {
        try await api.post("/v1/funding/link-bank", body: request)
    }

    func listAchRelationships() async throws -> [AchRelationshipDTO] {
        let response: AchRelationshipListResponse = try await api.get(
            "/v1/funding/ach-relationships"
        )
        return response.relationships
    }
}

/// Placeholder body for POST endpoints that take no parameters.
/// Encodes to `{}`.
private struct EmptyBody: Encodable {}
