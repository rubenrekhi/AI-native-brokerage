import Foundation

/// Payload for an MCP `TradeExecutionCard` surfaced in chat when the AI has prepared an order
/// and is awaiting user confirmation.
struct TradeExecutionCardData: Codable, Equatable, Hashable {
    let side: TradeSide
    let ticker: String
    let companyName: String
    let exchange: String
    let orderType: String
    let amount: String
    let estimatedShares: String
    let currentPrice: String
    let estimatedTotal: String
    let disclaimer: String
}

enum TradeSide: String, Codable, Equatable, Hashable {
    case buy
    case sell
}
