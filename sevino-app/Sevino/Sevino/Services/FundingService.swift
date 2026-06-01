import Foundation

/// Protocol for funding backend communication — enables mocking in tests.
protocol FundingServiceProtocol {
    func createLinkToken() async throws -> String
    func linkBank(_ request: LinkBankRequest) async throws -> AchRelationshipDTO
    func listAchRelationships() async throws -> [AchRelationshipDTO]
    func deleteAchRelationship(id: UUID) async throws
    func createReauthLinkToken(relationshipId: UUID) async throws -> String
    func completeReauth(relationshipId: UUID) async throws
    func createTransfer(
        relationshipId: String,
        amount: Decimal,
        direction: TransferDirection
    ) async throws -> TransferResponse
    func listTransfers() async throws -> [TransferResponse]
    func listDividends(limit: Int, offset: Int) async throws -> [DividendResponse]
    func getCashInterest() async throws -> CashInterestResponse
    func enrollCashInterest() async throws -> CashInterestResponse
}

final class FundingService: FundingServiceProtocol {
    static let shared = FundingService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func createLinkToken() async throws -> String {
        let response: LinkTokenResponse = try await api.post("/v1/funding/link-token")
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

    func deleteAchRelationship(id: UUID) async throws {
        try await api.delete("/v1/funding/ach-relationships/\(id.uuidString)")
    }

    func createReauthLinkToken(relationshipId: UUID) async throws -> String {
        let response: LinkTokenResponse = try await api.post(
            "/v1/funding/ach-relationships/\(relationshipId.uuidString)/reauth-link-token"
        )
        return response.linkToken
    }

    func completeReauth(relationshipId: UUID) async throws {
        try await api.post(
            "/v1/funding/ach-relationships/\(relationshipId.uuidString)/reauth-complete"
        )
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

    func listDividends(limit: Int = 50, offset: Int = 0) async throws -> [DividendResponse] {
        var components = URLComponents()
        components.path = "/v1/brokerage/dividends"
        components.queryItems = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
        guard let path = components.string else { throw URLError(.badURL) }

        let response: DividendListResponse = try await api.get(path)
        return response.dividends
    }

    func getCashInterest() async throws -> CashInterestResponse {
        try await api.get("/v1/brokerage/cash-interest")
    }

    func enrollCashInterest() async throws -> CashInterestResponse {
        try await api.post("/v1/brokerage/cash-interest/enroll")
    }
}

/// Placeholder body for POST endpoints that take no parameters.
/// Encodes to `{}`.
private struct EmptyBody: Encodable {}
