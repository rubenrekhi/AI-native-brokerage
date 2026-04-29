import Foundation

/// Mirrors the backend `OrderResponse`. Wire fields are strings (Alpaca's
/// shape) — use `qtyValue` / `submittedAtDate` / etc. to coerce when the UI
/// needs typed values.
struct OrderResponse: Decodable, Identifiable, Equatable {
    let id: String
    let clientOrderId: String?
    let symbol: String
    let assetClass: String?
    let side: String
    let orderType: String?
    let timeInForce: String?
    let qty: String?
    let notional: String?
    let filledQty: String?
    let filledAvgPrice: String?
    let limitPrice: String?
    let stopPrice: String?
    let status: String
    let submittedAt: String?
    let filledAt: String?
    let canceledAt: String?
    let expiredAt: String?
    let failedAt: String?
    let createdAt: String?

    var qtyValue: Decimal? { qty.flatMap { Decimal(string: $0) } }
    var filledQtyValue: Decimal? { filledQty.flatMap { Decimal(string: $0) } }
    var filledAvgPriceValue: Decimal? { filledAvgPrice.flatMap { Decimal(string: $0) } }
    var notionalValue: Decimal? { notional.flatMap { Decimal(string: $0) } }

    /// The most representative timestamp for sorting / display: the terminal
    /// event when the order is closed, otherwise the submission time.
    var representativeDate: Date? {
        let candidates = [filledAt, canceledAt, expiredAt, failedAt, submittedAt, createdAt]
        for candidate in candidates {
            if let date = candidate.flatMap(Self.parseISO8601) {
                return date
            }
        }
        return nil
    }

    var sideKind: OrderSide { OrderSide(apiValue: side) }
    var statusKind: TradeStatusKind { TradeStatusKind.from(status) }

    private static func parseISO8601(_ raw: String) -> Date? {
        Self.iso8601Fractional.date(from: raw) ?? Self.iso8601.date(from: raw)
    }

    private static let iso8601Fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
}

/// Wrapper for `GET /v1/brokerage/orders`.
struct OrderListResponse: Decodable {
    let orders: [OrderResponse]
}

/// Mirrors the backend `PositionResponse`. Used to populate the holdings
/// filter on the trade-history screen.
struct PositionResponse: Decodable, Equatable {
    let symbol: String
    let assetClass: String?
    let qty: String?
    let marketValue: String?
}

struct PositionListResponse: Decodable {
    let positions: [PositionResponse]
}

enum OrderSide: String {
    case buy
    case sell
    case unknown

    init(apiValue: String) {
        self = OrderSide(rawValue: apiValue.lowercased()) ?? .unknown
    }
}

/// Buckets Alpaca's many raw order statuses into the three pills the design
/// surfaces. Reference: https://docs.alpaca.markets/docs/orders-at-alpaca
enum TradeStatusKind {
    case completed
    case pending
    case failed
    case unknown

    static func from(_ raw: String) -> TradeStatusKind {
        switch raw.lowercased() {
        case "filled":
            return .completed
        case "new",
             "partially_filled",
             "accepted",
             "pending_new",
             "pending_replace",
             "pending_cancel",
             "replaced",
             "done_for_day",
             "accepted_for_bidding",
             "stopped",
             "calculated",
             "held":
            return .pending
        case "canceled",
             "cancelled",
             "expired",
             "rejected",
             "suspended":
            return .failed
        default:
            return .unknown
        }
    }
}

/// Filter selections persisted in the view model. The status filter buckets
/// to the three UI pills; the API request maps these to Alpaca's `open` /
/// `closed` / `all` status family.
enum TradeStatusFilter: Hashable, CaseIterable {
    case all
    case pending
    case completed
    case failed

    /// Maps the UI bucket to the `status` query param accepted by the
    /// backend. Pending → open (working orders); Completed/Failed → closed
    /// (Alpaca groups filled, canceled, rejected, etc. under "closed"); we
    /// then narrow client-side to the right bucket.
    var apiValue: String? {
        switch self {
        case .all: nil
        case .pending: "open"
        case .completed, .failed: "closed"
        }
    }
}

enum TradeSideFilter: Hashable, CaseIterable {
    case all
    case buy
    case sell

    var apiValue: String? {
        switch self {
        case .all: nil
        case .buy: "buy"
        case .sell: "sell"
        }
    }
}

enum TradeTimeframeFilter: Hashable, CaseIterable {
    case all
    case last7Days
    case last30Days
    case last90Days

    /// Lower bound for the `after` query param. `nil` means no lower bound.
    func afterDate(now: Date = .now) -> Date? {
        let calendar = Calendar(identifier: .gregorian)
        switch self {
        case .all: return nil
        case .last7Days: return calendar.date(byAdding: .day, value: -7, to: now)
        case .last30Days: return calendar.date(byAdding: .day, value: -30, to: now)
        case .last90Days: return calendar.date(byAdding: .day, value: -90, to: now)
        }
    }
}
