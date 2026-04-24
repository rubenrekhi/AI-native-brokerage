import Foundation

/// Decoded shape of `GET /v1/portfolio/holdings`.
///
/// `PositionDTO` is `Identifiable` keyed on symbol so SwiftUI `ForEach`
/// can render the list without a synthesized id.
struct HoldingsDTO: Decodable, Equatable {
    let accountStatus: String
    let currency: String
    @DecimalString var cash: Decimal
    @DecimalString var totalMarketValue: Decimal
    let positions: [PositionDTO]
}

struct PositionDTO: Decodable, Equatable, Identifiable {
    let symbol: String
    let name: String
    @DecimalString var qty: Decimal
    @DecimalString var avgEntryPrice: Decimal
    @DecimalString var currentPrice: Decimal
    @DecimalString var marketValue: Decimal
    @DecimalString var costBasis: Decimal
    @DecimalString var unrealizedPl: Decimal
    @DecimalString var unrealizedPlpc: Decimal

    var id: String { symbol }
}
