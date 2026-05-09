import Foundation

struct PortfolioCardData: Equatable {
    let equity: Decimal
    let currency: String
    let gainAbs: Decimal
    let gainPct: Decimal
    let chartPoints: [Double]
    let chartValues: [Decimal]
    let chartDates: [Date]
    let selectedTimeRange: TimeRange
    let hasLoaded: Bool
}
