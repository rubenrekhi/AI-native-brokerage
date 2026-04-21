import Foundation

@Observable
final class FundingViewModel {
    private let service: any FundingServiceProtocol

    private(set) var cashBalance = "—"
    private(set) var cashApy = "—"
    private(set) var cashThisMonth = "—"
    private(set) var cashDaysAccrued = "—"
    private(set) var cashLifetime = "—"
    private(set) var cashLifetimeSince = "—"
    private(set) var cashBuyingPower = "—"
    private(set) var cashPendingDeposits = "—"
    private(set) var cashInterestPaidOut = "—"
    private(set) var cashFdicInsured = "—"

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any FundingServiceProtocol = PlaceholderFundingService.shared) {
        self.service = service
    }

    func loadFundingData() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot = try await service.fetchFunding()
            cashBalance = snapshot.cashBalance
            cashApy = snapshot.cashApy
            cashThisMonth = snapshot.cashThisMonth
            cashDaysAccrued = snapshot.cashDaysAccrued
            cashLifetime = snapshot.cashLifetime
            cashLifetimeSince = snapshot.cashLifetimeSince
            cashBuyingPower = snapshot.cashBuyingPower
            cashPendingDeposits = snapshot.cashPendingDeposits
            cashInterestPaidOut = snapshot.cashInterestPaidOut
            cashFdicInsured = snapshot.cashFdicInsured
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }
}
