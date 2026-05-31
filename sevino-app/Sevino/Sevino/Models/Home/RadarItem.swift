import Foundation

/// UI model for a radar row. Mapped from `RadarItemDTO` by `RadarAPIClient`,
/// which formats the money/percent overlay into display strings and derives
/// the relative `expiresIn` label — the current `RadarCard` renders these
/// directly. `id` is the server row UUID, so star/delete can round-trip.
struct RadarItem: Identifiable, Equatable, Sendable {
    let id: UUID
    let ticker: String
    let companyName: String?
    let description: String
    let source: RadarSource
    let bucket: String?
    let relevanceScore: Float?
    let createdAt: Date
    var isStarred: Bool

    let price: String
    let changePercent: String
    let isPositive: Bool
    let expiresIn: String

    init(
        id: UUID = UUID(),
        ticker: String,
        companyName: String? = nil,
        description: String,
        source: RadarSource = .aiGenerated,
        bucket: String? = nil,
        relevanceScore: Float? = nil,
        createdAt: Date = Date(),
        isStarred: Bool,
        price: String,
        changePercent: String,
        isPositive: Bool,
        expiresIn: String
    ) {
        self.id = id
        self.ticker = ticker
        self.companyName = companyName
        self.description = description
        self.source = source
        self.bucket = bucket
        self.relevanceScore = relevanceScore
        self.createdAt = createdAt
        self.isStarred = isStarred
        self.price = price
        self.changePercent = changePercent
        self.isPositive = isPositive
        self.expiresIn = expiresIn
    }
}
