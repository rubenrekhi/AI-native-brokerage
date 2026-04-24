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

    // Call tracking
    private(set) var getProfileCalls = 0
    private(set) var getAccountValueCalls = 0
    private(set) var getSettingsCalls = 0
    private(set) var updateSettingsCalls: [UserSettingsPatchRequest] = []
    private(set) var updateProfileCalls: [ProfileUpdateRequest] = []
    private(set) var deleteAccountCalls = 0

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
}
