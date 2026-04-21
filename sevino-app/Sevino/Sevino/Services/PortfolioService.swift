import Foundation

/// A snapshot of portfolio display data for a given time range.
/// Values are pre-formatted strings because the backend is expected to return
/// them that way; chart points are unitless 0…1 values for the chart shape.
struct PortfolioSnapshot: Equatable {
    let displayValue: String
    let isDown: Bool
    let gainText: String
    let chartPoints: [Double]
}

/// Protocol for fetching portfolio data — enables mocking in previews and tests.
protocol PortfolioServiceProtocol {
    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot
}

/// Placeholder implementation that returns canned display values and generated
/// chart data. This is the default service used by `PortfolioViewModel` until
/// the backend endpoint exists — it is not a test double.
final class PlaceholderPortfolioService: PortfolioServiceProtocol {
    static let shared = PlaceholderPortfolioService()

    private let chartPointCount: Int

    init(chartPointCount: Int = 40) {
        self.chartPointCount = chartPointCount
    }

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        PortfolioSnapshot(
            displayValue: "$1,084.92",
            isDown: true,
            gainText: "+232.82 (+27.64%)",
            chartPoints: Self.generateChartPoints(count: chartPointCount)
        )
    }

    private static func generateChartPoints(count: Int) -> [Double] {
        guard count > 0 else { return [] }
        var points: [Double] = []
        var value = 0.15
        for _ in 0..<count {
            value += Double.random(in: -0.03...0.05)
            value = max(0.05, min(1.0, value))
            points.append(value)
        }
        if points.count >= 3 {
            points[points.count - 1] = 0.92
            points[points.count - 2] = 0.88
            points[points.count - 3] = 0.95
        }
        return points
    }
}
