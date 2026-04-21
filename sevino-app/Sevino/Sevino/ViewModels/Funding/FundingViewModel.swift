import Foundation
import Observation

/// Observable state for the Plaid + ACH funding flow.
///
/// Composed onto `HomeViewModel.funding` so `FundingMorphingView` can keep a
/// single `viewModel: HomeViewModel` parameter.
@Observable
final class FundingViewModel {

    // MARK: - Network state

    var relationships: [AchRelationshipDTO] = []
    var isLoading: Bool = false

    // MARK: - Error state
    //
    // `serverError` is populated when APIClient decodes a non-2xx body into
    // APIError. `localError` holds anything client-side (Plaid exit error,
    // unexpected throw). Views bind to `displayedError` — a coalesced string.

    var serverError: APIError?
    var localError: String?

    // MARK: - Plaid sheet state

    var linkToken: String?
    var isShowingPlaidLink: Bool = false

    private let service: any FundingServiceProtocol

    init(service: any FundingServiceProtocol = FundingService.shared) {
        self.service = service
    }

    // MARK: - Derived

    /// Drives the CTA branch in `FundingMorphingView`.
    var hasLinkedBank: Bool { !relationships.isEmpty }

    /// Single string the inline banner renders. Server error wins if both set —
    /// server messages are more specific than the generic local fallback.
    var displayedError: String? {
        serverError?.localizedDescription ?? localError
    }

    /// Clear both error sources. Called at the start of any user-initiated
    /// operation that should reset the banner.
    func clearErrors() {
        serverError = nil
        localError = nil
    }

    // MARK: - Actions

    /// Called when the `$` modal expands.
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

    /// Called when the user taps "Link a bank account".
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

    /// Called from PlaidLinkSheet's onSuccess.
    /// Awaits `loadRelationships()` BEFORE flipping `isShowingPlaidLink` false
    /// so the action row has already re-rendered as Deposit/Withdraw by the
    /// time the sheet dismisses.
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
            // On BANK_ALREADY_LINKED, refresh so UI catches up with server state.
            if apiError.code == "BANK_ALREADY_LINKED" {
                await loadRelationships()
            }
        } catch {
            localError = L10n.Home.fundingGenericError
        }
        linkToken = nil
        isShowingPlaidLink = false
    }

    /// Called from PlaidLinkSheet's onExit.
    /// nil error = user-cancelled (silent). Non-nil = surface a generic banner.
    func onPlaidExit(error plaidError: Error?) {
        if plaidError != nil {
            localError = L10n.Home.fundingPlaidConnectionError
        }
        linkToken = nil
        isShowingPlaidLink = false
    }
}
