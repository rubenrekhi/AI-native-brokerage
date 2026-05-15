import Foundation

/// Lightweight value capturing which modal was open and its snapshot data
/// so the chat can render the card inline as a user-message attachment.
enum AttachedContext: Equatable, Sendable {
    case portfolio(equity: Decimal, currency: String, gainAbs: Decimal, gainPct: Decimal, timeRange: String)
    case holdings(holdings: [HoldingSummary])
    case funding(balance: Decimal, apy: Decimal, buyingPower: Decimal)
    case radar(items: [RadarSummary])

    /// Convert to the wire-format dict sent as `context` in the chat turn request.
    var wireContext: [String: JSONValue] {
        switch self {
        case .portfolio(let equity, let currency, let gainAbs, let gainPct, let timeRange):
            return [
                "type": .string("portfolio"),
                "equity": .string("\(equity)"),
                "currency": .string(currency),
                "gain_abs": .string("\(gainAbs)"),
                "gain_pct": .string("\(gainPct)"),
                "time_range": .string(timeRange),
            ]
        case .funding(let balance, let apy, let buyingPower):
            return [
                "type": .string("funding"),
                "balance": .string("\(balance)"),
                "apy": .string("\(apy)"),
                "buying_power": .string("\(buyingPower)"),
            ]
        case .holdings(let holdings):
            let list: [JSONValue] = holdings.map { h in
                var entry: [String: JSONValue] = [
                    "ticker": .string(h.ticker),
                    "market_value": .string("\(h.marketValue)"),
                ]
                if let pl = h.unrealizedPl { entry["unrealized_pl"] = .string("\(pl)") }
                return .object(entry)
            }
            return [
                "type": .string("holdings"),
                "holdings": .array(list),
            ]
        case .radar(let items):
            let list: [JSONValue] = items.map { item in
                .object([
                    "ticker": .string(item.ticker),
                    "description": .string(item.description),
                    "price": .string(item.price),
                    "change_percent": .string(item.changePercent),
                    "is_positive": .bool(item.isPositive),
                ])
            }
            return [
                "type": .string("radar"),
                "items": .array(list),
            ]
        }
    }
}

struct HoldingSummary: Identifiable, Equatable, Sendable {
    var id: String { ticker }
    let ticker: String
    let marketValue: Decimal
    let unrealizedPl: Decimal?
}

struct RadarSummary: Identifiable, Equatable, Sendable {
    var id: String { ticker }
    let ticker: String
    let description: String
    let price: String
    let changePercent: String
    let isPositive: Bool
}
