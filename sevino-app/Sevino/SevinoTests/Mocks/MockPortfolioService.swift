import Foundation
@testable import Sevino

final class MockPortfolioService: PortfolioServiceProtocol {
    var fetchPortfolioError: Error?
    var snapshot = PortfolioSnapshot(
        displayValue: "$1,000.00",
        isDown: false,
        gainText: "+$10.00 (+1.00%)",
        chartPoints: [0.1, 0.2, 0.3]
    )

    private(set) var fetchPortfolioCallCount = 0
    private(set) var fetchPortfolioRanges: [TimeRange] = []

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        fetchPortfolioCallCount += 1
        fetchPortfolioRanges.append(range)
        if let error = fetchPortfolioError { throw error }
        return snapshot
    }
}
