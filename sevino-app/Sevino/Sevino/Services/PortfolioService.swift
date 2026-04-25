import Foundation

/// View-model snapshot of portfolio data for the home screen.
///
/// Stores raw `Decimal` values straight from `/v1/portfolio/snapshot` so
/// formatting happens at render time (via `NumberFormatting`), which keeps
/// locale + sign handling in one place. The string-shaped properties
/// (`displayValue`, `gainText`, `isDown`) are kept as computed accessors so
/// existing view callsites compile unchanged.
///
/// `chartPoints` lives here rather than on a separate snapshot type because
/// `PortfolioViewModel` consumes a single `PortfolioSnapshot` today;
/// history-driven points are merged in via F4.8 when the chart endpoint is
/// wired up.
struct PortfolioSnapshot: Equatable {
    let accountStatus: String
    let equity: Decimal
    let dailyChangeAbs: Decimal
    let dailyChangePct: Decimal
    let chartPoints: [Double]

    var displayValue: String { equity.asCurrency() }
    var isDown: Bool { dailyChangeAbs < 0 }
    var gainText: String {
        "\(dailyChangeAbs.asSignedCurrency()) (\(dailyChangePct.asSignedPercent()))"
    }
}

/// Protocol for fetching portfolio data — enables mocking in previews and tests.
protocol PortfolioServiceProtocol {
    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot
}

/// Default real implementation. Calls `GET /v1/portfolio/snapshot` and maps
/// `PortfolioSnapshotDTO` into the view-model `PortfolioSnapshot`. The
/// snapshot endpoint is range-agnostic — `range` is accepted to satisfy the
/// protocol but ignored. Range-specific chart data comes from F4.8.
final class APIPortfolioService: PortfolioServiceProtocol {
    static let shared = APIPortfolioService()
    private let client: any APIClientProtocol

    init(client: any APIClientProtocol = APIClient.shared) {
        self.client = client
    }

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        let dto: PortfolioSnapshotDTO = try await client.get("/v1/portfolio/snapshot")
        return PortfolioSnapshot(
            accountStatus: dto.accountStatus,
            equity: dto.equity,
            dailyChangeAbs: dto.dailyChangeAbs,
            dailyChangePct: dto.dailyChangePct,
            chartPoints: []
        )
    }
}

/// Returns canned values for SwiftUI Previews and offline development. Not a
/// test double — production code reaches `APIPortfolioService.shared`.
final class PlaceholderPortfolioService: PortfolioServiceProtocol {
    static let shared = PlaceholderPortfolioService()

    private let chartPointCount: Int

    init(chartPointCount: Int = 40) {
        self.chartPointCount = chartPointCount
    }

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        PortfolioSnapshot(
            accountStatus: "ACTIVE",
            equity: Decimal(string: "1084.92")!,
            dailyChangeAbs: Decimal(string: "232.82")!,
            dailyChangePct: Decimal(string: "0.2731")!,
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
