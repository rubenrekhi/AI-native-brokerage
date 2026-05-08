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

    // MARK: - Cash display state

    private(set) var cashBalance: Decimal = 0
    private(set) var cashApy: Decimal = 0
    private(set) var cashThisMonthEarned: Decimal = 0
    private(set) var cashDaysAccrued: Int = 0
    private(set) var cashLifetimeEarned: Decimal = 0
    private(set) var cashLifetimeSince: Date?
    private(set) var cashBuyingPower: Decimal = 0
    private(set) var cashPendingDeposits: Decimal = 0
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

    func loadCashInterest() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await service.getCashInterest()
            cashBalance = Decimal(string: response.balance) ?? 0
            cashApy = Decimal(string: response.apy) ?? 0
            cashThisMonthEarned = Decimal(string: response.thisMonthEarned) ?? 0
            cashDaysAccrued = response.daysAccrued
            cashLifetimeEarned = Decimal(string: response.lifetimeEarned) ?? 0
            cashBuyingPower = Decimal(string: response.buyingPower) ?? 0
            cashPendingDeposits = Decimal(string: response.pendingDeposits) ?? 0
            cashFdicInsuredLimit = Decimal(string: response.fdicInsuredLimit) ?? 2_500_000
            cashLifetimeSince = response.lifetimeSinceDate
            cashInterestPaidOut = PaidOutCadence(rawValue: response.interestPaidOut) ?? .monthly
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
