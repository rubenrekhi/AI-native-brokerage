import Foundation
@testable import Sevino

final class MockOnboardingService: OnboardingServiceProtocol {
    var saveStepError: Error?
    var submitError: Error?
    var statusError: Error?

    var submitResponse = OnboardingSubmitResponse(accountStatus: "APPROVED", alpacaAccountId: "acc_123")
    var statusResponse = OnboardingStatusResponse()

    private(set) var savedSteps: [OnboardingPatchRequest] = []
    private(set) var submittedTaxIds: [String] = []
    private(set) var getStatusCallCount = 0

    func saveStep(_ request: OnboardingPatchRequest) async throws {
        savedSteps.append(request)
        if let error = saveStepError { throw error }
    }

    func submit(taxId: String) async throws -> OnboardingSubmitResponse {
        submittedTaxIds.append(taxId)
        if let error = submitError { throw error }
        return submitResponse
    }

    func getStatus() async throws -> OnboardingStatusResponse {
        getStatusCallCount += 1
        if let error = statusError { throw error }
        return statusResponse
    }
}
