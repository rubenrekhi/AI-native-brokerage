import Foundation

/// Protocol for fetching settings-screen data — enables mocking in previews and tests.
protocol SettingsServiceProtocol {
    func getProfile() async throws -> SettingsProfileResponse
    func getAccountValue() async throws -> AccountValueResponse
}

/// Default implementation. Profile is sourced from the onboarding status endpoint,
/// which already carries the fields rendered on the settings screens. Account
/// value is canned until the portfolio endpoint exists; `SettingsViewModel`
/// can swap in a real implementation without changing shape.
final class SettingsService: SettingsServiceProtocol {
    static let shared = SettingsService()

    private let onboardingService: any OnboardingServiceProtocol

    init(onboardingService: any OnboardingServiceProtocol = OnboardingService.shared) {
        self.onboardingService = onboardingService
    }

    func getProfile() async throws -> SettingsProfileResponse {
        let status = try await onboardingService.getStatus()
        let profile = status.profile
        let displayName = Self.displayName(from: profile)
        return SettingsProfileResponse(
            displayName: displayName,
            email: profile?.email,
            phoneNumber: profile?.phoneNumber,
            kycStatus: status.accountStatus
        )
    }

    func getAccountValue() async throws -> AccountValueResponse {
        AccountValueResponse(totalValue: "$0.00", cashBalance: "$0.00")
    }

    private static func displayName(from profile: ProfileData?) -> String {
        let candidates = [profile?.preferredName, profile?.firstName]
        return candidates
            .compactMap { $0 }
            .first { !$0.isEmpty } ?? ""
    }
}
