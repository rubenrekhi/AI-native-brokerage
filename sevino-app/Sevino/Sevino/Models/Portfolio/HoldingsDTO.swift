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
    @DecimalString var buyingPower: Decimal
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
    /// Position-level $ gain today: `(current_price − lastday_price) × qty`.
    /// Same unit as `unrealizedPl`. Computed server-side; render directly.
    @DecimalString var changeToday: Decimal
    /// Today's % move on the ticker (factor of 1, e.g. 0.0084 = 0.84%).
    /// Pinned to 0 when the server can't compute a usable previous close.
    @DecimalString var changeTodayPercent: Decimal
}
