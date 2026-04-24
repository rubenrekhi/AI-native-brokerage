import Foundation

/// Protocol for funding backend communication — enables mocking in tests.
protocol FundingServiceProtocol {
    func createLinkToken() async throws -> String
    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO
    func listAchRelationships() async throws -> [AchRelationshipDTO]
    func createTransfer(
        relationshipId: String,
        amount: Decimal,
        direction: TransferDirection
    ) async throws -> TransferResponse
    func listTransfers() async throws -> [TransferResponse]
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

    func createTransfer(
        relationshipId: String,
        amount: Decimal,
        direction: TransferDirection
    ) async throws -> TransferResponse {
        try await api.post(
            "/v1/funding/transfers",
            body: TransferRequest(
                relationshipId: relationshipId,
                amount: Self.formatAmount(amount),
                direction: direction.apiValue
            )
        )
    }

    /// Fixed-point decimal string formatter for the wire format. Uses en_US_POSIX to
    /// guarantee a `.` decimal separator and no thousands grouping regardless of the
    /// user's locale — the backend parses these as literal decimal strings.
    private static func formatAmount(_ amount: Decimal) -> String {
        amount.formatted(
            .number
                .precision(.fractionLength(2))
                .grouping(.never)
                .locale(Locale(identifier: "en_US_POSIX"))
        )
    }

    func listTransfers() async throws -> [TransferResponse] {
        let response: TransferListResponse = try await api.get("/v1/funding/transfers")
        return response.transfers
    }
}

/// Placeholder body for POST endpoints that take no parameters.
/// Encodes to `{}`.
private struct EmptyBody: Encodable {}
