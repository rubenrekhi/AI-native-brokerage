import Foundation

struct Holding: Equatable, Identifiable {
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
