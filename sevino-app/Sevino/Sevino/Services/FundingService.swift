import Foundation

/// A snapshot of funding/cash display data. Values are pre-formatted strings
/// because the backend is expected to return them that way.
struct FundingSnapshot: Equatable {
    let cashBalance: String
    let cashApy: String
    let cashThisMonth: String
    let cashDaysAccrued: String
    let cashLifetime: String
    let cashLifetimeSince: String
    let cashBuyingPower: String
    let cashPendingDeposits: String
    let cashInterestPaidOut: String
    let cashFdicInsured: String
}

/// Protocol for fetching funding data — enables mocking in previews and tests.
protocol FundingServiceProtocol {
    func fetchFunding() async throws -> FundingSnapshot
}

/// Placeholder implementation that returns canned display values. This is the
/// default service used by `FundingViewModel` until the backend endpoint exists
/// — it is not a test double.
final class PlaceholderFundingService: FundingServiceProtocol {
    static let shared = PlaceholderFundingService()

    func fetchFunding() async throws -> FundingSnapshot {
        FundingSnapshot(
            cashBalance: "$2,412.08",
            cashApy: "3.20%",
            cashThisMonth: "+$6.43",
            cashDaysAccrued: "22",
            cashLifetime: "+$41.87",
            cashLifetimeSince: "Oct 2025",
            cashBuyingPower: "$2,412.08",
            cashPendingDeposits: "$100.50",
            cashInterestPaidOut: "Monthly",
            cashFdicInsured: "$2,500,000"
        )
    }
}
