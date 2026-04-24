import Foundation

/// Decoded shape of `GET /v1/portfolio/snapshot`.
///
/// Money fields arrive as JSON strings ("120.50") and are decoded to
/// `Decimal` via `@DecimalString` to avoid Double precision loss. Wire
/// keys are snake_case; APIClient's decoder uses `.convertFromSnakeCase`
/// so Swift property names stay camelCase.
struct PortfolioSnapshotDTO: Decodable, Equatable {
    let accountStatus: String
    let currency: String
    @DecimalString var equity: Decimal
    @DecimalString var lastEquity: Decimal
    @DecimalString var cash: Decimal
    @DecimalString var buyingPower: Decimal
    @DecimalString var dailyChangeAbs: Decimal
    @DecimalString var dailyChangePct: Decimal
}
