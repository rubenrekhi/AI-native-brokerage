import Foundation
@testable import Sevino

final class MockSettingsService: SettingsServiceProtocol, @unchecked Sendable {

    // Stubs
    var getProfileResult: Result<SettingsProfileResponse, Error>?
    var getAccountValueResult: Result<AccountValueResponse, Error>?
    var getSettingsResult: Result<UserSettingsDTO, Error>?
    var updateSettingsResult: Result<UserSettingsDTO, Error>?
    var updateProfileResult: Result<SettingsProfileResponse, Error>?
    var deleteAccountResult: Result<Void, Error> = .success(())
    var closeBrokerageAccountResult: Result<Void, Error> = .success(())

    /// Optional async handler. When set, it's awaited instead of evaluating
    /// `closeBrokerageAccountResult` — lets tests hold the call in-flight.
    var closeBrokerageAccountHandler: (@Sendable () async throws -> Void)?

    var listDocumentsResult: Result<[DocumentDTO], Error> = .success([])
    var downloadDocumentResult: Result<URL, Error>?
    var downloadDocumentHandler: ((String) async throws -> URL)?
    var documentDownloadURLBase = "https://example.invalid/v1/settings/documents"

    // Call tracking
    private(set) var getProfileCalls = 0
    private(set) var getAccountValueCalls = 0
    private(set) var getSettingsCalls = 0
    private(set) var updateSettingsCalls: [UserSettingsPatchRequest] = []
    private(set) var updateProfileCalls: [ProfileUpdateRequest] = []
    private(set) var deleteAccountCalls = 0
    private(set) var closeBrokerageAccountCalls = 0
    private(set) var listDocumentsCalls: [String?] = []
    private(set) var documentDownloadURLCalls: [String] = []
    private(set) var downloadDocumentCalls: [String] = []

    func getProfile() async throws -> SettingsProfileResponse {
        getProfileCalls += 1
        guard let result = getProfileResult else {
            fatalError("getProfile called but no result stubbed")
        }
        return try result.get()
    }

    func getAccountValue() async throws -> AccountValueResponse {
        getAccountValueCalls += 1
        guard let result = getAccountValueResult else {
            fatalError("getAccountValue called but no result stubbed")
        }
        return try result.get()
    }

    func getSettings() async throws -> UserSettingsDTO {
        getSettingsCalls += 1
        guard let result = getSettingsResult else {
            fatalError("getSettings called but no result stubbed")
        }
        return try result.get()
    }

    func updateSettings(_ request: UserSettingsPatchRequest) async throws -> UserSettingsDTO {
        updateSettingsCalls.append(request)
        guard let result = updateSettingsResult else {
            fatalError("updateSettings called but no result stubbed")
        }
        return try result.get()
    }

    func updateProfile(_ request: ProfileUpdateRequest) async throws -> SettingsProfileResponse {
        updateProfileCalls.append(request)
        guard let result = updateProfileResult else {
            fatalError("updateProfile called but no result stubbed")
        }
        return try result.get()
    }

    func deleteAccount() async throws {
        deleteAccountCalls += 1
        try deleteAccountResult.get()
    }

    func closeBrokerageAccount() async throws {
        closeBrokerageAccountCalls += 1
        if let handler = closeBrokerageAccountHandler {
            try await handler()
            return
        }
        try closeBrokerageAccountResult.get()
    }

    func listDocuments(type: String?) async throws -> [DocumentDTO] {
        listDocumentsCalls.append(type)
        return try listDocumentsResult.get()
    }

    func documentDownloadURL(id: String) -> URL {
        documentDownloadURLCalls.append(id)
        guard let url = URL(string: "\(documentDownloadURLBase)/\(id)/download") else {
            preconditionFailure("Invalid mock URL for id=\(id)")
        }
        return url
    }

    func downloadDocument(id: String) async throws -> URL {
        downloadDocumentCalls.append(id)
        if let handler = downloadDocumentHandler {
            return try await handler(id)
        }
        guard let result = downloadDocumentResult else {
            fatalError("downloadDocument called but no result stubbed")
        }
        return try result.get()
    }
}
