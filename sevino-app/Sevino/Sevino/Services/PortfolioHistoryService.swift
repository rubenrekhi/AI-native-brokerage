import Foundation

/// Range-scoped time series for the portfolio chart.
///
/// `chartPoints` is a min-max normalized 0...1 projection of `points.v` for the
/// existing `PortfolioChartView`, which expects `[Double]`. Raw `Decimal` values
/// stay on `points` so future scrub readouts can format them via
/// `NumberFormatting`.
struct PortfolioHistorySeries: Equatable {
    let range: TimeRange
    let baseValue: Decimal
    let endValue: Decimal
    let gainAbs: Decimal
    let gainPct: Decimal
    let points: [PortfolioHistoryPoint]
    let chartPoints: [Double]
}

protocol PortfolioHistoryServiceProtocol: Sendable {
    func fetchHistory(for range: TimeRange) async throws -> PortfolioHistorySeries
}

/// Default real implementation. Calls `GET /v1/portfolio/history?range=...` and
/// projects `PortfolioHistoryDTO` into a chart-ready `PortfolioHistorySeries`.
final class APIPortfolioHistoryService: PortfolioHistoryServiceProtocol {
    static let shared = APIPortfolioHistoryService()
    private let client: any APIClientProtocol

    init(client: any APIClientProtocol = APIClient.shared) {
        self.client = client
    }

    func fetchHistory(for range: TimeRange) async throws -> PortfolioHistorySeries {
        let dto: PortfolioHistoryDTO = try await client.get(
            "/v1/portfolio/history",
            query: ["range": range.rawValue]
        )
        return PortfolioHistorySeries(
            range: range,
            baseValue: dto.baseValue,
            endValue: dto.endValue,
            gainAbs: dto.gainAbs,
            gainPct: dto.gainPct,
            points: dto.points,
            chartPoints: Self.normalize(dto.points)
        )
    }

    /// Min-max normalize values into 0...1 for the chart view. A flat series
    /// (single value or all equal) collapses to 0.5 so the line renders mid-card
    /// instead of pinning to the bottom.
    private static func normalize(_ points: [PortfolioHistoryPoint]) -> [Double] {
        let values = points.map { NSDecimalNumber(decimal: $0.v).doubleValue }
        guard let min = values.min(), let max = values.max(), max > min else {
            return Array(repeating: 0.5, count: values.count)
        }
        return values.map { ($0 - min) / (max - min) }
    }
}

/// Returns canned values for SwiftUI Previews and offline development. Mirrors
/// `PlaceholderPortfolioService`'s synthetic chart so previews look the same
/// as before history wiring.
final class PlaceholderPortfolioHistoryService: PortfolioHistoryServiceProtocol {
    static let shared = PlaceholderPortfolioHistoryService()

    private let chartPointCount: Int

    init(chartPointCount: Int = 40) {
        self.chartPointCount = chartPointCount
    }

    func fetchHistory(for range: TimeRange) async throws -> PortfolioHistorySeries {
        PortfolioHistorySeries(
            range: range,
            baseValue: Decimal(string: "1000.00")!,
            endValue: Decimal(string: "1290.00")!,
            gainAbs: Decimal(string: "290.00")!,
            gainPct: Decimal(string: "0.2900")!,
            points: [],
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
