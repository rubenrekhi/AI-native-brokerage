import Foundation
@testable import Sevino

final class MockPortfolioService: PortfolioServiceProtocol {
    var fetchPortfolioError: Error?
    var snapshot = PortfolioSnapshot(
        equity: Decimal(string: "1000.00")!,
        currency: "USD",
        gainAbs: Decimal(string: "10.00")!,
        gainPct: Decimal(string: "0.01")!,
        chartPoints: [0.1, 0.2, 0.3],
        chartValues: [Decimal(800), Decimal(900), Decimal(1000)],
        chartDates: [
            Date(timeIntervalSince1970: 1700000000),
            Date(timeIntervalSince1970: 1700001000),
            Date(timeIntervalSince1970: 1700002000)
        ]
    )

    var fetchSnapshotError: Error?
    var pillUpdate = PortfolioPillUpdate(
        equity: Decimal(string: "1000.00")!,
        currency: "USD",
        dailyChangeAbs: Decimal(string: "5.00")!,
        dailyChangePct: Decimal(string: "0.005")!
    )

    private(set) var fetchPortfolioCallCount = 0
    private(set) var fetchPortfolioRanges: [TimeRange] = []
    private(set) var fetchSnapshotCallCount = 0

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        fetchPortfolioCallCount += 1
        fetchPortfolioRanges.append(range)
        if let error = fetchPortfolioError { throw error }
        return snapshot
    }

    func fetchSnapshot() async throws -> PortfolioPillUpdate {
        fetchSnapshotCallCount += 1
        if let error = fetchSnapshotError { throw error }
        return pillUpdate
    }
}
