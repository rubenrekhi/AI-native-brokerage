import Foundation
@testable import Sevino

final class MockHoldingsService: HoldingsServiceProtocol {
    var fetchHoldingsError: Error?
    var holdings: [Holding] = []
    var accountStatus: String = "ACTIVE"

    private(set) var fetchHoldingsCallCount = 0

    func fetchHoldings() async throws -> HoldingsResult {
        fetchHoldingsCallCount += 1
        if let error = fetchHoldingsError { throw error }
        return HoldingsResult(accountStatus: accountStatus, holdings: holdings)
    }
}
