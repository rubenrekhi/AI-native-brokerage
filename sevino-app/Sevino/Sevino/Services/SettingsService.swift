import Foundation

/// Protocol for settings backend communication — enables mocking in tests.
protocol SettingsServiceProtocol {
    func getProfile() async throws -> SettingsProfileResponse
    func getAccountValue() async throws -> AccountValueResponse
    func getSettings() async throws -> UserSettingsDTO
    func updateSettings(_ request: UserSettingsPatchRequest) async throws -> UserSettingsDTO
    func updateProfile(_ request: ProfileUpdateRequest) async throws -> SettingsProfileResponse
    func deleteAccount() async throws
    func listDocuments(type: String?) async throws -> [DocumentDTO]
    func documentDownloadURL(id: String) -> URL
    func downloadDocument(id: String) async throws -> URL
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
        try await api.delete("/v1/settings/account", body: ["confirmation": "DELETE"])
    }

    func listDocuments(type: String?) async throws -> [DocumentDTO] {
        var path = "/v1/settings/documents"
        if let type, !type.isEmpty,
           let encoded = type.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            path += "?type=\(encoded)"
        }
        let response: DocumentListResponse = try await api.get(path)
        return response.documents
    }

    /// Absolute URL for the document download endpoint — intended for callers
    /// that want to hand the URL to Safari / UIActivityViewController. The
    /// in-app viewer uses `downloadDocument(id:)` instead, which issues the
    /// authenticated request.
    func documentDownloadURL(id: String) -> URL {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        let absolute = AppConfig.apiBaseURL + "/v1/settings/documents/\(encoded)/download"
        guard let url = URL(string: absolute) else {
            preconditionFailure("Invalid document download URL for id=\(id)")
        }
        return url
    }

    func downloadDocument(id: String) async throws -> URL {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await api.downloadFile(
            "/v1/settings/documents/\(encoded)/download",
            suggestedExtension: "pdf"
        )
    }
}
