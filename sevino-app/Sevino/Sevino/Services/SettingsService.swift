import Foundation

/// Protocol for settings backend communication — enables mocking in tests.
protocol SettingsServiceProtocol {
    func getProfile() async throws -> SettingsProfileResponse
    func getAccountValue() async throws -> AccountValueResponse
    func getSettings() async throws -> UserSettingsDTO
    func updateSettings(_ request: UserSettingsPatchRequest) async throws -> UserSettingsDTO
    func updateProfile(_ request: ProfileUpdateRequest) async throws -> SettingsProfileResponse
    func deleteAccount() async throws
}

/// Handles backend communication for the settings screen: profile, account value,
/// app preferences, and account deletion.
final class SettingsService: SettingsServiceProtocol {
    static let shared = SettingsService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func getProfile() async throws -> SettingsProfileResponse {
        try await api.get("/v1/settings/profile")
    }

    func getAccountValue() async throws -> AccountValueResponse {
        try await api.get("/v1/settings/account-value")
    }

    func getSettings() async throws -> UserSettingsDTO {
        try await api.get("/v1/settings")
    }

    func updateSettings(_ request: UserSettingsPatchRequest) async throws -> UserSettingsDTO {
        try await api.patch("/v1/settings", body: request)
    }

    func updateProfile(_ request: ProfileUpdateRequest) async throws -> SettingsProfileResponse {
        try await api.patch("/v1/settings/profile", body: request)
    }

    func deleteAccount() async throws {
        try await api.delete("/v1/settings/account")
    }
}
