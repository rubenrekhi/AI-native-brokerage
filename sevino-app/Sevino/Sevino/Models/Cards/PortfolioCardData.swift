import Foundation

struct PortfolioCardData: Codable, Equatable {
    let displayValue: String
    let isDown: Bool
    let gainText: String
    let periodLabel: String
    let chartPoints: [Double]
    let selectedTimeRange: TimeRange
}
