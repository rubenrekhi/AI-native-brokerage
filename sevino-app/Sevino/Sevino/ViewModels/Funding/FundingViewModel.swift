import Foundation
import Observation

/// Observable state for the Plaid + ACH funding flow.

@Observable
final class FundingViewModel {

    // MARK: - Network state

    var relationships: [AchRelationshipDTO] = []
    var isLoading: Bool = false
    var serverError: APIError?
    var localError: String?
    let plaidLink: PlaidLinkCoordinator

    // MARK: - Cash display (mock) state

    private(set) var cashBalance: Decimal = 2412.08
    private(set) var cashApy: Decimal = 0.032
    private(set) var cashThisMonthEarned: Decimal = 6.43
    private(set) var cashDaysAccrued: Int = 22
    private(set) var cashLifetimeEarned: Decimal = 41.87
    private(set) var cashLifetimeSince: Date = DateComponents(
        calendar: .current, year: 2025, month: 10, day: 1
    ).date ?? Date()
    private(set) var cashBuyingPower: Decimal = 2412.08
    private(set) var cashPendingDeposits: Decimal = 100.50
    private(set) var cashInterestPaidOut: PaidOutCadence = .monthly
    private(set) var cashFdicInsuredLimit: Decimal = 2_500_000

    private let service: any FundingServiceProtocol

    init(service: any FundingServiceProtocol = FundingService.shared) {
        self.service = service
        self.plaidLink = PlaidLinkCoordinator(service: service)
        self.plaidLink.onLinked = { [weak self] in
            await self?.loadRelationships()
        }
    }

    // MARK: - Derived

    var hasLinkedBank: Bool { !relationships.isEmpty }

    /// Coalesces relationship-load errors with Plaid-flow errors so views can
    /// observe a single error stream regardless of which call failed.
    var displayedError: String? {
        plaidLink.displayedError ?? serverError?.localizedDescription ?? localError
    }

    var error: String? { displayedError }
    func clearError() { clearErrors() }

    func clearErrors() {
        serverError = nil
        localError = nil
        plaidLink.clearErrors()
    }

    // MARK: - Actions

    func loadRelationships() async {
        isLoading = true
        defer { isLoading = false }
        do {
            relationships = try await service.listAchRelationships()
        } catch let apiError as APIError {
            serverError = apiError
        } catch {
            localError = L10n.Home.fundingGenericError
        }
    }

    /// Exposed so callers continue to drive the link flow through the VM
    /// (preserves the existing `viewModel.requestBankLink` call site).
    func requestBankLink() {
        plaidLink.requestBankLink()
    }
}
