import Foundation

/// One row in the user's live brokerage account: either the synthetic CASH row
/// (`isCash == true`) or a real position. Decoded from `/v1/portfolio/holdings`
/// via `HoldingsDTO`, so all monetary fields are `Decimal` (formatting happens
/// at the view layer via `NumberFormatting`).
///
/// Distinct from the chat-rendered `Holding` (in `Views/Components/Cards/`)
/// which carries pre-formatted strings — that type is for MCP card payloads
/// and has different lifecycle and update semantics. Don't merge them.
struct PortfolioHolding: Equatable, Identifiable {
    var id: String { ticker }

    let ticker: String
    let isCash: Bool
    let name: String

    let qty: Decimal?
    let marketValue: Decimal
    let avgEntryPrice: Decimal?
    let unrealizedPl: Decimal?
    let unrealizedPlpc: Decimal?

    var valueText: String { marketValue.asCurrency() }
    var sharesText: String? { qty?.asShareCount() }
    var isPositive: Bool? { unrealizedPl.map { $0 >= 0 } }
    var gainLossText: String? {
        guard let pl = unrealizedPl, let pct = unrealizedPlpc else { return nil }
        return "\(pl.asSignedCurrency()) (\(pct.asSignedPercent()))"
    }
    var averageCostText: String? { avgEntryPrice?.asCurrency() }
}
