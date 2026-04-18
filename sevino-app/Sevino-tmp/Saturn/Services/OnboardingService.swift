import Foundation

/// Protocol for onboarding backend communication — enables mocking in tests and ViewModels.
protocol OnboardingServiceProtocol {
    func saveStep(_ request: OnboardingPatchRequest) async throws
    func submit(taxId: String) async throws -> OnboardingSubmitResponse
    func getStatus() async throws -> OnboardingStatusResponse
}

/// Handles all backend communication for the onboarding and KYC flows.
final class OnboardingService: OnboardingServiceProtocol {
    static let shared = OnboardingService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func saveStep(_ request: OnboardingPatchRequest) async throws {
        let _: OnboardingPatchResponse = try await api.patch("/v1/onboarding", body: request)
    }

    func submit(taxId: String) async throws -> OnboardingSubmitResponse {
        try await api.post("/v1/onboarding/submit", body: OnboardingSubmitRequest(taxId: taxId))
    }

    func getStatus() async throws -> OnboardingStatusResponse {
        try await api.get("/v1/onboarding/status")
    }
}
