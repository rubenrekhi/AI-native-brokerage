import Foundation
@testable import Sevino

final class MockOnboardingService: OnboardingServiceProtocol {
    var errorToThrow: Error?
    var statusToReturn: OnboardingStatusResponse?
    var submitResponseToReturn: OnboardingSubmitResponse?

    private(set) var saveStepCallCount = 0
    private(set) var lastSavedRequest: OnboardingPatchRequest?
    private(set) var getStatusCallCount = 0
    private(set) var submitCallCount = 0

    func saveStep(_ request: OnboardingPatchRequest) async throws {
        saveStepCallCount += 1
        lastSavedRequest = request
        if let error = errorToThrow { throw error }
    }

    func submit(taxId: String) async throws -> OnboardingSubmitResponse {
        submitCallCount += 1
        if let error = errorToThrow { throw error }
        return submitResponseToReturn ?? OnboardingSubmitResponse(
            accountStatus: "SUBMITTED",
            alpacaAccountId: "alpaca-test"
        )
    }

    func getStatus() async throws -> OnboardingStatusResponse {
        getStatusCallCount += 1
        if let error = errorToThrow { throw error }
        return statusToReturn ?? OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: nil,
            accountStatus: nil,
            profile: nil,
            financialProfile: nil
        )
    }
}
