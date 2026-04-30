import Foundation
@testable import Sevino

final class MockHoldingsService: HoldingsServiceProtocol {
    var fetchHoldingsError: Error?
    var holdings: [Holding] = []

    private(set) var fetchHoldingsCallCount = 0

    func fetchHoldings() async throws -> [Holding] {
        fetchHoldingsCallCount += 1
        if let error = fetchHoldingsError { throw error }
        return holdings
    }
}
