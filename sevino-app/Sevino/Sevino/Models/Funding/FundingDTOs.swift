import Foundation

/// Response from POST /v1/funding/link-token.
struct LinkTokenResponse: Decodable {
    let linkToken: String
}

/// Body for POST /v1/funding/link-bank.
/// Field names match the backend schema in app/schemas/funding.py; snake_case
/// conversion is handled by APIClient's encoder.
struct LinkBankRequest: Encodable {
    let publicToken: String
    let accountId: String
    let institutionName: String?
    let accountMask: String?
    let accountName: String?
    let nickname: String?
}

/// Response for POST /v1/funding/link-bank and entries in
/// GET /v1/funding/ach-relationships.
struct AchRelationshipDTO: Decodable, Identifiable, Equatable {
    let id: UUID
    let alpacaRelationshipId: String
    let institutionName: String?
    let accountMask: String?
    let accountType: String?
    let nickname: String?
    let status: String
}
