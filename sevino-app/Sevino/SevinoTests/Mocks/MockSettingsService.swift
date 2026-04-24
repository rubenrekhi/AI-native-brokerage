import Foundation
@testable import Sevino

final class MockSettingsService: SettingsServiceProtocol, @unchecked Sendable {

    var profileResult: Result<SettingsProfileResponse, Error> = .success(
        SettingsProfileResponse(
            displayName: "Riley",
            email: "riley@sevino.ai",
            phoneNumber: "+1 (555) 555-5555",
            kycStatus: "approved"
        )
    )
    var accountValueResult: Result<AccountValueResponse, Error> = .success(
        AccountValueResponse(totalValue: "$1,000.00", cashBalance: "$500.00")
    )

    private(set) var getProfileCalls = 0
    private(set) var getAccountValueCalls = 0

    func getProfile() async throws -> SettingsProfileResponse {
        getProfileCalls += 1
        return try profileResult.get()
    }

    func getAccountValue() async throws -> AccountValueResponse {
        getAccountValueCalls += 1
        return try accountValueResult.get()
    }
}
