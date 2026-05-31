import Foundation

/// Whether a radar row was hand-added by the user or surfaced by the weekly
/// AI batch. Mirrors the backend `RadarSource` literal in
/// `app/schemas/radar.py`.
enum RadarSource: String, Decodable, Sendable {
    case userAdded = "user_added"
    case aiGenerated = "ai_generated"
}

/// Wire shape of a single row from `/v1/radar`, mirroring the backend
/// `RadarItemRead`. The `price` / `changeAbs` / `changePct` overlay fields
/// are populated only on GET (the service merges live quotes in); POST and
/// PATCH responses leave them null.
struct RadarItemDTO: Decodable, Equatable, Sendable {
    let id: UUID
    let symbol: String
    let companyName: String?
    let contextBlurb: String?
    let source: RadarSource
    let bucket: String?
    let isFavorited: Bool
    let relevanceScore: Float?
    let expiresAt: Date?
    let createdAt: Date

    @DecimalStringOptional var price: Decimal?
    @DecimalStringOptional var changeAbs: Decimal?
    /// Today's move as a factor of 1 (0.0124 == +1.24%), per the backend
    /// `PctStr` convention.
    @DecimalStringOptional var changePct: Decimal?
}

/// Wire shape of `GET /v1/radar`, mirroring the backend `RadarListResponse`.
/// `nextRefreshAt` is null until the user's first batch is enqueued.
struct RadarListResponseDTO: Decodable, Equatable, Sendable {
    let items: [RadarItemDTO]
    let nextRefreshAt: Date?
}
