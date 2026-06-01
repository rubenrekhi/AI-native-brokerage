#if DEBUG
import Foundation
import Observation

struct PreviewUnimplemented: Error {}

/// SettingsService stub that returns a fixed profile/account snapshot for SwiftUI previews.
final class PreviewLoadedSettingsService: SettingsServiceProtocol, @unchecked Sendable {
    static let profileJSON = Data("""
    {
      "profile": {
        "preferred_name": "Ready Riley",
        "first_name": "Riley",
        "last_name": "Ready",
        "email": "ready.riley@sevino.ai",
        "phone_number": "+11234567890",
        "street_address": ["123 Invest Circle"],
        "city": "Cleveland",
        "state": "OH",
        "postal_code": "44110"
      },
      "financial_profile": {
        "risk_scenario_response": "buy_more",
        "max_loss_tolerance": "40%+"
      },
      "brokerage": null,
      "linked_accounts": [],
      "member_since": "2026-01-15T00:00:00Z"
    }
    """.utf8)

    static func decodedProfile() -> SettingsProfileResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // swiftlint:disable:next force_try
        return try! decoder.decode(SettingsProfileResponse.self, from: profileJSON)
    }

    func getProfile() async throws -> SettingsProfileResponse {
        Self.decodedProfile()
    }

    func getAccountValue() async throws -> AccountValueResponse {
        AccountValueResponse(equity: 0, cash: 0, buyingPower: 0, portfolioValue: 0)
    }

    func getSettings() async throws -> UserSettingsDTO {
        UserSettingsDTO(theme: .system, textSize: .regular, notificationsEnabled: true, aiInternetAccess: true)
    }

    func updateSettings(_: UserSettingsPatchRequest) async throws -> UserSettingsDTO {
        try await getSettings()
    }

    func updateProfile(_: ProfileUpdateRequest) async throws -> SettingsProfileResponse {
        try await getProfile()
    }

    func deleteAccount() async throws {}
    func closeBrokerageAccount() async throws {}

    func listDocuments(type _: String?) async throws -> [DocumentDTO] { [] }
    func documentDownloadURL(id: String) -> URL {
        URL(string: "https://example.invalid/v1/settings/documents/\(id)/download")!
    }
    func downloadDocument(id _: String) async throws -> URL { throw PreviewUnimplemented() }
}

/// SettingsService stub that never resolves, used to render loading previews.
final class PreviewStallingSettingsService: SettingsServiceProtocol, @unchecked Sendable {
    func getProfile() async throws -> SettingsProfileResponse {
        try await Task.sleep(for: .seconds(60))
        throw PreviewUnimplemented()
    }
    func getAccountValue() async throws -> AccountValueResponse {
        try await Task.sleep(for: .seconds(60))
        throw PreviewUnimplemented()
    }
    func getSettings() async throws -> UserSettingsDTO { throw PreviewUnimplemented() }
    func updateSettings(_: UserSettingsPatchRequest) async throws -> UserSettingsDTO { throw PreviewUnimplemented() }
    func updateProfile(_: ProfileUpdateRequest) async throws -> SettingsProfileResponse { throw PreviewUnimplemented() }
    func deleteAccount() async throws {}
    func closeBrokerageAccount() async throws {}
    func listDocuments(type _: String?) async throws -> [DocumentDTO] {
        try await Task.sleep(for: .seconds(60))
        throw PreviewUnimplemented()
    }
    func documentDownloadURL(id: String) -> URL {
        URL(string: "https://example.invalid/v1/settings/documents/\(id)/download")!
    }
    func downloadDocument(id _: String) async throws -> URL { throw PreviewUnimplemented() }
}

/// SettingsService stub that always fails the profile load, used to render error previews.
final class PreviewFailingSettingsService: SettingsServiceProtocol, @unchecked Sendable {
    func getProfile() async throws -> SettingsProfileResponse { throw PreviewUnimplemented() }
    func getAccountValue() async throws -> AccountValueResponse { throw PreviewUnimplemented() }
    func getSettings() async throws -> UserSettingsDTO { throw PreviewUnimplemented() }
    func updateSettings(_: UserSettingsPatchRequest) async throws -> UserSettingsDTO { throw PreviewUnimplemented() }
    func updateProfile(_: ProfileUpdateRequest) async throws -> SettingsProfileResponse { throw PreviewUnimplemented() }
    func deleteAccount() async throws {}
    func closeBrokerageAccount() async throws {}
    func listDocuments(type _: String?) async throws -> [DocumentDTO] { throw PreviewUnimplemented() }
    func documentDownloadURL(id: String) -> URL {
        URL(string: "https://example.invalid/v1/settings/documents/\(id)/download")!
    }
    func downloadDocument(id _: String) async throws -> URL { throw PreviewUnimplemented() }
}

/// AuthService stub for SwiftUI previews. Defaults to authenticated; `signIn` flips
/// the flag to mimic the live listener. Most write methods are no-ops; `verifyError`
/// and `verifyDelaySeconds` exist so previews can render the alert and the spinner
/// states of the email verification screen without a live backend.
@Observable
final class PreviewAuthService: AuthServiceProtocol {
    var isAuthenticated: Bool
    var isEmailVerified: Bool = false
    var emailResendAvailableAt: Date?
    var canResendEmailConfirmation: Bool { true }
    var accessToken: String? { nil }
    var currentEmail: String? { "preview@example.com" }

    /// When non-nil, `verifyEmailConfirmation` throws this error instead of
    /// flipping `isEmailVerified`. Used to preview the "invalid code" alert.
    var verifyError: Error?
    /// When > 0, `verifyEmailConfirmation` sleeps that many seconds before
    /// resolving — used to preview the `isConfirming` spinner state.
    var verifyDelaySeconds: Int = 0

    init(isAuthenticated: Bool = true) {
        self.isAuthenticated = isAuthenticated
    }

    func signUp(email: String, password: String) async throws {}
    func signIn(email: String, password: String) async throws { isAuthenticated = true }
    func signOut() async throws { isAuthenticated = false }
    func updatePassword(currentPassword: String, newPassword: String) async throws {}
    func resendEmailConfirmation(email: String) async throws {}
    func verifyEmailConfirmation(email: String, code: String) async throws {
        if verifyDelaySeconds > 0 {
            try? await Task.sleep(for: .seconds(verifyDelaySeconds))
        }
        if let verifyError { throw verifyError }
        isEmailVerified = true
    }
}

/// FundingService stub that satisfies the protocol without performing any work.
final class PreviewNoopFundingService: FundingServiceProtocol, @unchecked Sendable {
    func createLinkToken() async throws -> String { "" }
    func linkBank(_: LinkBankRequest) async throws -> AchRelationshipDTO { throw PreviewUnimplemented() }
    func listAchRelationships() async throws -> [AchRelationshipDTO] { [] }
    func deleteAchRelationship(id _: UUID) async throws {}
    func createReauthLinkToken(relationshipId _: UUID) async throws -> String { "" }
    func completeReauth(relationshipId _: UUID) async throws {}
    func createTransfer(
        relationshipId _: String,
        amount _: Decimal,
        direction _: TransferDirection
    ) async throws -> TransferResponse { throw PreviewUnimplemented() }
    func listTransfers() async throws -> [TransferResponse] { [] }
    func listDividends(limit _: Int, offset _: Int) async throws -> [DividendResponse] { [] }
    func getCashInterest() async throws -> CashInterestResponse {
        CashInterestResponse(
            balance: "0",
            apy: "0",
            thisMonthEarned: "0",
            daysAccrued: 0,
            lifetimeEarned: "0",
            lifetimeSince: nil,
            buyingPower: "0",
            pendingDeposits: "0",
            interestPaidOut: "monthly",
            fdicInsuredLimit: "2500000",
            sweepStatus: nil,
            enrollmentState: .active
        )
    }
}
#endif
