import Foundation

/// Decoded shape of `GET /v1/portfolio/history?range=...`.
///
/// `PortfolioHistoryPoint.t` is decoded from ISO-8601 strings via the
/// `dateDecodingStrategy = .iso8601` configured globally in `APIClient`.
/// The backend always emits UTC; `.iso8601` accepts both `Z` and
/// `+00:00` offsets.
struct PortfolioHistoryDTO: Decodable, Equatable {
    let range: String
    let timeframe: String
    let currency: String
    @DecimalString var baseValue: Decimal
    @DecimalString var endValue: Decimal
    @DecimalString var gainAbs: Decimal
    @DecimalString var gainPct: Decimal
    let points: [PortfolioHistoryPoint]
}

struct PortfolioHistoryPoint: Decodable, Equatable {
    let t: Date
    @DecimalString var v: Decimal
}
