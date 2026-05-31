import Foundation

/// Hand-mirrored discriminated union for `app/services/digest/cards.py`.
/// The backend uses `kind` as the discriminator and sends money / quantity /
/// percent values as decimal strings.
enum DigestCard: Codable, Identifiable, Equatable, Sendable {
    case dividends(DividendsDigestCard)
    case pendingOrderActivity(PendingOrderActivityDigestCard)
    case bigMove(BigMoveDigestCard)
    case watchlistMove(WatchlistMoveDigestCard)
    case marketContext(MarketContextDigestCard)
    case radarRefresh(RadarRefreshDigestCard)
    case earningsResult(EarningsResultDigestCard)
    case upcomingEarnings(UpcomingEarningsDigestCard)
    case news(NewsDigestCard)

    var id: UUID {
        switch self {
        case .dividends(let card): return card.id
        case .pendingOrderActivity(let card): return card.id
        case .bigMove(let card): return card.id
        case .watchlistMove(let card): return card.id
        case .marketContext(let card): return card.id
        case .radarRefresh(let card): return card.id
        case .earningsResult(let card): return card.id
        case .upcomingEarnings(let card): return card.id
        case .news(let card): return card.id
        }
    }

    var kind: String {
        switch self {
        case .dividends: return "dividends"
        case .pendingOrderActivity: return "pending_order_activity"
        case .bigMove: return "big_move"
        case .watchlistMove: return "watchlist_move"
        case .marketContext: return "market_context"
        case .radarRefresh: return "radar_refresh"
        case .earningsResult: return "earnings_result"
        case .upcomingEarnings: return "upcoming_earnings"
        case .news: return "news"
        }
    }

    var priority: Int {
        switch self {
        case .dividends(let card): return card.priority
        case .pendingOrderActivity(let card): return card.priority
        case .bigMove(let card): return card.priority
        case .watchlistMove(let card): return card.priority
        case .marketContext(let card): return card.priority
        case .radarRefresh(let card): return card.priority
        case .earningsResult(let card): return card.priority
        case .upcomingEarnings(let card): return card.priority
        case .news(let card): return card.priority
        }
    }

    var relatedSymbols: [String] {
        switch self {
        case .dividends(let card): return card.relatedSymbols
        case .pendingOrderActivity(let card): return card.relatedSymbols
        case .bigMove(let card): return card.relatedSymbols
        case .watchlistMove(let card): return card.relatedSymbols
        case .marketContext(let card): return card.relatedSymbols
        case .radarRefresh(let card): return card.relatedSymbols
        case .earningsResult(let card): return card.relatedSymbols
        case .upcomingEarnings(let card): return card.relatedSymbols
        case .news(let card): return card.relatedSymbols
        }
    }

    var cardContext: [String: JSONValue] {
        switch self {
        case .dividends(let card): return card.cardContext
        case .pendingOrderActivity(let card): return card.cardContext
        case .bigMove(let card): return card.cardContext
        case .watchlistMove(let card): return card.cardContext
        case .marketContext(let card): return card.cardContext
        case .radarRefresh(let card): return card.cardContext
        case .earningsResult(let card): return card.cardContext
        case .upcomingEarnings(let card): return card.cardContext
        case .news(let card): return card.cardContext
        }
    }

    private enum DiscriminatorKey: String, CodingKey {
        case kind
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: DiscriminatorKey.self)
        let kind = try container.decode(String.self, forKey: .kind)
        switch kind {
        case "dividends":
            self = .dividends(try DividendsDigestCard(from: decoder))
        case "pending_order_activity":
            self = .pendingOrderActivity(try PendingOrderActivityDigestCard(from: decoder))
        case "big_move":
            self = .bigMove(try BigMoveDigestCard(from: decoder))
        case "watchlist_move":
            self = .watchlistMove(try WatchlistMoveDigestCard(from: decoder))
        case "market_context":
            self = .marketContext(try MarketContextDigestCard(from: decoder))
        case "radar_refresh":
            self = .radarRefresh(try RadarRefreshDigestCard(from: decoder))
        case "earnings_result":
            self = .earningsResult(try EarningsResultDigestCard(from: decoder))
        case "upcoming_earnings":
            self = .upcomingEarnings(try UpcomingEarningsDigestCard(from: decoder))
        case "news":
            self = .news(try NewsDigestCard(from: decoder))
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .kind,
                in: container,
                debugDescription: "Unknown digest card kind: \(kind)"
            )
        }
    }

    func encode(to encoder: any Encoder) throws {
        var kindContainer = encoder.container(keyedBy: DiscriminatorKey.self)
        switch self {
        case .dividends(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .pendingOrderActivity(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .bigMove(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .watchlistMove(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .marketContext(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .radarRefresh(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .earningsResult(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .upcomingEarnings(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        case .news(let card):
            try kindContainer.encode(kind, forKey: .kind)
            try card.encode(to: encoder)
        }
    }
}

struct DividendPaymentDTO: Codable, Identifiable, Equatable, Sendable {
    let symbol: String
    @DecimalString var amount: Decimal
    let paidAt: Date

    var id: String {
        "\(symbol)-\(paidAt.timeIntervalSince1970)"
    }
}

struct OrderActivityItemDTO: Codable, Identifiable, Equatable, Sendable {
    let symbol: String
    let name: String?
    let side: String?
    @DecimalStringOptional var qty: Decimal?
    @DecimalStringOptional var notional: Decimal?

    var id: String {
        [
            symbol,
            name ?? "",
            side ?? "",
            qty?.description ?? "",
            notional?.description ?? ""
        ].joined(separator: "|")
    }
}

struct DividendsDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let payments: [DividendPaymentDTO]
    @DecimalString var totalAmount: Decimal
    let periodLabel: String
}

struct PendingOrderActivityDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let filled: [OrderActivityItemDTO]
    let recurringExecuted: [OrderActivityItemDTO]
    let recurringSkipped: [OrderActivityItemDTO]
}

struct BigMoveDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let symbol: String
    let name: String
    @DecimalString var prevClose: Decimal
    @DecimalString var current: Decimal
    @DecimalString var changeAbs: Decimal
    @DecimalString var changePct: Decimal
    let reason: String?
}

struct WatchlistMoveDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let symbol: String
    let name: String
    @DecimalString var prevClose: Decimal
    @DecimalString var current: Decimal
    @DecimalString var changeAbs: Decimal
    @DecimalString var changePct: Decimal
    let reason: String?
}

struct MarketContextDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let direction: String
    @DecimalString var sp500ChangePct: Decimal
    @DecimalString var nasdaqChangePct: Decimal
    let summary: String
}

struct RadarRefreshDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let refreshedAt: Date
    let newCount: Int
    let removedCount: Int
}

struct EarningsResultDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let symbol: String
    let name: String
    let grade: String
    @DecimalStringOptional var epsActual: Decimal?
    @DecimalStringOptional var epsEstimate: Decimal?
    @DecimalStringOptional var revActual: Decimal?
    @DecimalStringOptional var revEstimate: Decimal?
    @DecimalStringOptional var stockReactionPct: Decimal?
    let beatMissHighlights: [String]
}

struct UpcomingEarningsDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let symbol: String
    let name: String
    let reportsAt: Date
    let relativeLabel: String
}

struct NewsDigestCard: Codable, Equatable, Sendable {
    let id: UUID
    let priority: Int
    let relatedSymbols: [String]
    let cardContext: [String: JSONValue]
    let symbol: String?
    let headline: String
    let source: String
    let url: String
    let publishedAt: Date
    let summary: String
}

/// Flexible wire representation of a Daily Digest card passed into chat.
///
/// The digest rendering module owns the concrete card variants. Chat only
/// needs to preserve the card object exactly enough for the backend to inject
/// it into the LLM context, so this wrapper encodes as the underlying JSON
/// object rather than as `{ "payload": ... }`.
struct ChatDigestCard: Codable, Equatable, Sendable {
    let payload: [String: JSONValue]

    init(payload: [String: JSONValue]) {
        self.payload = payload
    }

    init(id: String, kind: String, fields: [String: JSONValue] = [:]) {
        var payload = fields
        payload["id"] = .string(id)
        payload["kind"] = .string(kind)
        self.payload = payload
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        payload = try container.decode([String: JSONValue].self)
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(payload)
    }
}
