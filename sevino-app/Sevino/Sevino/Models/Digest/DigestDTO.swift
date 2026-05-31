import Foundation

/// Wire shape for `GET /v1/digest/today`.
/// `nyLocalDate` is a plain `YYYY-MM-DD` string because the app only needs to
/// identify the snapshot's local day; timestamp fields remain `Date`.
struct DigestTodayResponseDTO: Decodable, Equatable, Sendable {
    let snapshot: DigestSnapshotDTO
    let peekVisible: Bool
}

struct DigestSnapshotDTO: Decodable, Equatable, Sendable {
    let id: UUID
    let nyLocalDate: String
    let cards: [DigestCard]
    let generatedAt: Date
    let dismissedAt: Date?
    let createdAt: Date
}
