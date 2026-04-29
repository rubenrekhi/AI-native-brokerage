import Foundation
@testable import Sevino

final class MockPortfolioHistoryService: PortfolioHistoryServiceProtocol {
    var fetchHistoryError: Error?
    var series = PortfolioHistorySeries(
        range: .oneMonth,
        baseValue: Decimal(string: "1000.00")!,
        endValue: Decimal(string: "1290.00")!,
        gainAbs: Decimal(string: "290.00")!,
        gainPct: Decimal(string: "0.2900")!,
        points: [],
        chartPoints: [0.1, 0.5, 0.9]
    )

    private(set) var fetchHistoryCallCount = 0
    private(set) var fetchHistoryRanges: [TimeRange] = []

    func fetchHistory(for range: TimeRange) async throws -> PortfolioHistorySeries {
        fetchHistoryCallCount += 1
        fetchHistoryRanges.append(range)
        if let error = fetchHistoryError { throw error }
        return series
    }
}
