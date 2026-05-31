import Foundation

/// The user's radar list plus the cadence anchor. `nextRefreshAt` drives the
/// "next batch arrives {weekday}" empty-state copy (consumed in T8b).
struct RadarListResponse: Equatable, Sendable {
    let items: [RadarItem]
    let nextRefreshAt: Date?
}

/// Networked access to `/v1/radar/*`. Returns UI-ready `RadarItem`s — the
/// wire decoding and money/percent formatting happen here so the view models
/// stay free of `RadarItemDTO`.
protocol RadarAPIClientProtocol: Sendable {
    func fetchRadar() async throws -> RadarListResponse
    /// PATCH the favorite flag. Returns the updated row on 200, or nil on 204
    /// — the server deletes the row when a `user_added` item is unfavorited.
    func toggleFavorite(itemId: UUID, isFavorited: Bool) async throws -> RadarItem?
    func deleteRadarItem(itemId: UUID) async throws
    func addRadarItem(symbol: String) async throws -> RadarItem
}

struct RadarAPIClient: RadarAPIClientProtocol {
    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func fetchRadar() async throws -> RadarListResponse {
        let dto: RadarListResponseDTO = try await api.get("/v1/radar")
        let now = Date()
        return RadarListResponse(
            items: dto.items.map { RadarAPIClient.item(from: $0, now: now) },
            nextRefreshAt: dto.nextRefreshAt
        )
    }

    func toggleFavorite(itemId: UUID, isFavorited: Bool) async throws -> RadarItem? {
        let dto: RadarItemDTO? = try await api.patchOptional(
            "/v1/radar/\(itemId.uuidString)",
            body: RadarFavoriteUpdate(isFavorited: isFavorited)
        )
        return dto.map { RadarAPIClient.item(from: $0, now: Date()) }
    }

    func deleteRadarItem(itemId: UUID) async throws {
        try await api.delete("/v1/radar/\(itemId.uuidString)")
    }

    func addRadarItem(symbol: String) async throws -> RadarItem {
        let dto: RadarItemDTO = try await api.post(
            "/v1/radar",
            body: RadarItemAdd(symbol: symbol)
        )
        return RadarAPIClient.item(from: dto, now: Date())
    }

    /// Fold a wire row into the display model. The PATCH/POST overlay fields
    /// (`price`/`changePct`) arrive null off the create/update paths, so those
    /// display strings come back empty there and are filled on the next GET.
    static func item(from dto: RadarItemDTO, now: Date) -> RadarItem {
        RadarItem(
            id: dto.id,
            ticker: dto.symbol,
            companyName: dto.companyName,
            description: dto.contextBlurb ?? "",
            source: dto.source,
            bucket: dto.bucket,
            relevanceScore: dto.relevanceScore,
            createdAt: dto.createdAt,
            isStarred: dto.isFavorited,
            price: dto.price?.asCurrency() ?? "",
            changePercent: dto.changePct?.asSignedPercent() ?? "",
            isPositive: (dto.changePct ?? 0) >= 0,
            expiresIn: Self.expiresIn(until: dto.expiresAt, from: now)
        )
    }

    /// "6 days" / "5 hours" / "20 minutes". Empty when there is no expiry
    /// (user-added rows) or the row has already lapsed — the current card
    /// hides the label in that case.
    static func expiresIn(until expiresAt: Date?, from now: Date) -> String {
        guard let expiresAt else { return "" }
        let seconds = expiresAt.timeIntervalSince(now)
        guard seconds > 0 else { return "" }
        let days = Int(seconds / 86_400)
        if days >= 1 { return days == 1 ? "1 day" : "\(days) days" }
        let hours = Int(seconds / 3_600)
        if hours >= 1 { return hours == 1 ? "1 hour" : "\(hours) hours" }
        let minutes = max(1, Int(seconds / 60))
        return minutes == 1 ? "1 minute" : "\(minutes) minutes"
    }
}

private struct RadarFavoriteUpdate: Encodable {
    let isFavorited: Bool
}

private struct RadarItemAdd: Encodable {
    let symbol: String
}

/// Canned `RadarAPIClientProtocol` for SwiftUI previews. Not a test double —
/// it returns a fixed batch so `RadarViewModel`-backed previews render without
/// hitting the network.
struct PlaceholderRadarAPIClient: RadarAPIClientProtocol {
    func fetchRadar() async throws -> RadarListResponse {
        RadarListResponse(items: Self.sampleItems, nextRefreshAt: nil)
    }

    func toggleFavorite(itemId: UUID, isFavorited: Bool) async throws -> RadarItem? {
        Self.sampleItems.first { $0.id == itemId }
    }

    func deleteRadarItem(itemId: UUID) async throws {}

    func addRadarItem(symbol: String) async throws -> RadarItem {
        RadarItem(
            ticker: symbol, description: "", source: .userAdded, isStarred: true,
            price: "", changePercent: "", isPositive: true, expiresIn: ""
        )
    }

    private static let sampleItems: [RadarItem] = [
        RadarItem(
            ticker: "TSLA",
            description: "Automotive tech leader you asked about last week, earnings in 2 days.",
            isStarred: false,
            price: "$274.63", changePercent: "+1.24%", isPositive: true, expiresIn: "6 days"
        ),
        RadarItem(
            ticker: "NVDA",
            description: "AI chip giant with record data center revenue, up 180% this year.",
            isStarred: false,
            price: "$892.41", changePercent: "+2.67%", isPositive: true, expiresIn: "3 days"
        ),
        RadarItem(
            ticker: "AAPL",
            description: "iPhone maker nearing $4T market cap, services revenue accelerating.",
            isStarred: true,
            price: "$198.11", changePercent: "-0.43%", isPositive: false, expiresIn: "5 days"
        ),
        RadarItem(
            ticker: "AMZN",
            description: "Cloud and retail leader with AWS growth reaccelerating to 19%.",
            isStarred: false,
            price: "$186.49", changePercent: "+0.91%", isPositive: true, expiresIn: "4 days"
        ),
    ]
}
