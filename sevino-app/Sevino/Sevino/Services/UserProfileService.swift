import Foundation

/// Protocol for fetching the current user's profile — enables mocking in previews and tests.
protocol UserProfileServiceProtocol {
    func fetchPreferredName() async throws -> String
}

/// Placeholder implementation that returns a canned preferred name. This is the default
/// service used by `HomeViewModel` until the backend endpoint exists — it is
/// not a test double.
final class PlaceholderUserProfileService: UserProfileServiceProtocol {
    static let shared = PlaceholderUserProfileService()

    func fetchPreferredName() async throws -> String {
        "Riley"
    }
}
