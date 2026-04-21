import Foundation
@testable import Sevino

final class MockFundingService: FundingServiceProtocol {
    var fetchFundingError: Error?
    var snapshot = FundingSnapshot(
        cashBalance: "$100.00",
        cashApy: "3.00%",
        cashThisMonth: "+$1.00",
        cashDaysAccrued: "10",
        cashLifetime: "+$5.00",
        cashLifetimeSince: "Jan 2026",
        cashBuyingPower: "$100.00",
        cashPendingDeposits: "$0.00",
        cashInterestPaidOut: "Monthly",
        cashFdicInsured: "$2,500,000"
    )

    private(set) var fetchFundingCallCount = 0

    func fetchFunding() async throws -> FundingSnapshot {
        fetchFundingCallCount += 1
        if let error = fetchFundingError { throw error }
        return snapshot
    }
}
