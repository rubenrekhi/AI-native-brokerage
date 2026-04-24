import Foundation
import Observation

/// Observable state for the Plaid + ACH funding flow.

@Observable
final class FundingViewModel {

    // MARK: - Network state

    var relationships: [AchRelationshipDTO] = []
    var isLoading: Bool = false

    // MARK: - Error state

    var serverError: APIError?
    var localError: String?

    // MARK: - Plaid sheet state

    var linkToken: String?
    var isShowingPlaidLink: Bool = false

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
    }

    // MARK: - Derived

    var hasLinkedBank: Bool { !relationships.isEmpty }

    var displayedError: String? {
        serverError?.localizedDescription ?? localError
    }

    var error: String? { displayedError }
    func clearError() { clearErrors() }

    func clearErrors() {
        serverError = nil
        localError = nil
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

    func requestBankLink() {
        Task { await startBankLink() }
    }

    func startBankLink() async {
        clearErrors()
        isLoading = true
        defer { isLoading = false }
        do {
            linkToken = try await service.createLinkToken()
            isShowingPlaidLink = true
        } catch let apiError as APIError {
            serverError = apiError
        } catch {
            localError = L10n.Home.fundingGenericError
        }
    }

    func onPlaidSuccess(
        publicToken: String,
        accountId: String,
        institutionName: String?,
        accountMask: String?,
        accountName: String?
    ) async {
        do {
            _ = try await service.linkBank(
                LinkBankRequest(
                    publicToken: publicToken,
                    accountId: accountId,
                    institutionName: institutionName,
                    accountMask: accountMask,
                    accountName: accountName,
                    nickname: nil
                )
            )
            await loadRelationships()
        } catch let apiError as APIError {
            serverError = apiError
            if apiError.code == "BANK_ALREADY_LINKED" {
                await loadRelationships()
            }
        } catch {
            localError = L10n.Home.fundingGenericError
        }
        linkToken = nil
        isShowingPlaidLink = false
    }

    func onPlaidExit(error plaidError: Error?) {
        if plaidError != nil {
            localError = L10n.Home.fundingPlaidConnectionError
        }
        linkToken = nil
        isShowingPlaidLink = false
    }
}
