import Foundation

/// Decoded shape of `GET /v1/portfolio/holdings`.
///
/// `PositionDTO` does not conform to `Identifiable`: a single account can
/// hold both long and short legs of the same symbol, and a future
/// multi-account view would surface duplicates across accounts. SwiftUI
/// `ForEach` callers should key on a composite identifier (e.g. account
/// id + symbol + side) at the call site instead.
struct HoldingsDTO: Decodable, Equatable {
    let accountStatus: String
    let currency: String
    @DecimalString var cash: Decimal
    @DecimalString var totalMarketValue: Decimal
    let positions: [PositionDTO]
}

struct PositionDTO: Decodable, Equatable {
    let symbol: String
    let name: String
    @DecimalString var qty: Decimal
    @DecimalString var avgEntryPrice: Decimal
    @DecimalString var currentPrice: Decimal
    @DecimalString var marketValue: Decimal
    @DecimalString var costBasis: Decimal
    @DecimalString var unrealizedPl: Decimal
    @DecimalString var unrealizedPlpc: Decimal
}
