import Foundation
import Observation

/// Owns the Plaid Link sheet state and the orchestration around fetching a
/// link token, presenting the sheet, and forwarding the resulting public token
/// to the API. Both `FundingViewModel` (Home) and `SettingsViewModel`
/// (Linked Accounts) hold one of these — wiring `onLinked` to whatever each
/// screen needs to refresh after a successful link.
@Observable
@MainActor
final class PlaidLinkCoordinator {

    // MARK: - State

    private(set) var linkToken: String?
    private(set) var isShowingPlaidLink: Bool = false
    private(set) var isLoading: Bool = false
    private(set) var serverError: APIError?
    private(set) var localError: String?

    private let service: any FundingServiceProtocol

    /// Called after a successful link (and after `BANK_ALREADY_LINKED`, so the
    /// caller's UI can reflect the existing account instead of going stale).
    var onLinked: () async -> Void = {}

    // MARK: - Derived

    var displayedError: String? {
        serverError?.localizedDescription ?? localError
    }

    /// Bindable driver for an `.alert(isPresented:)` over the link error.
    /// Setter clears both error channels on dismiss so the alert can't re-fire.
    var showError: Bool {
        get { displayedError != nil }
        set { if !newValue { clearErrors() } }
    }

    /// Bindable driver for the Plaid `.sheet`. Setter clears `linkToken` on
    /// dismiss so the sheet can't re-present stale state.
    var showPlaidLink: Bool {
        get { isShowingPlaidLink }
        set {
            isShowingPlaidLink = newValue
            if !newValue { linkToken = nil }
        }
    }

    init(service: any FundingServiceProtocol = FundingService.shared) {
        self.service = service
    }

    // MARK: - Actions

    func clearErrors() {
        serverError = nil
        localError = nil
    }

    /// Fire-and-forget convenience for SwiftUI button actions.
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
            await onLinked()
        } catch let apiError as APIError {
            serverError = apiError
            // The bank already exists on this user — refresh anyway so the UI
            // reflects reality instead of leaving the (already-linked) account
            // missing from the list.
            if apiError.code == "BANK_ALREADY_LINKED" {
                await onLinked()
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
