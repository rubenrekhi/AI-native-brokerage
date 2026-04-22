import Foundation

/// Protocol for fetching the current user's profile — enables mocking in previews and tests.
protocol UserProfileServiceProtocol {
    /// Returns the user's preferred first name, or `nil` if none is set.
    func fetchPreferredName() async throws -> String?
}

/// Fetches the user's profile from the backend via the onboarding status endpoint,
/// which already carries the preferred and legal first names saved during onboarding.
final class UserProfileService: UserProfileServiceProtocol {
    static let shared = UserProfileService()

    private let onboardingService: any OnboardingServiceProtocol

    init(onboardingService: any OnboardingServiceProtocol = OnboardingService.shared) {
        self.onboardingService = onboardingService
    }

    func fetchPreferredName() async throws -> String? {
        let status = try await onboardingService.getStatus()
        let candidates = [status.profile?.preferredName, status.profile?.firstName]
        return candidates
            .compactMap { $0 }
            .first { !$0.isEmpty }
    }
}
