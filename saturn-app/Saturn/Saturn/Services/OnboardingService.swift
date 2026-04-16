import Foundation

/// Handles all backend communication for the onboarding and KYC flows.
final class OnboardingService {
    static let shared = OnboardingService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    /// Save a single onboarding step's data to the backend.
    func saveStep(_ request: OnboardingPatchRequest) async throws {
        let _: OnboardingPatchResponse = try await api.patch("/v1/onboarding", body: request)
    }

    /// Submit KYC to Alpaca. SSN is forwarded and never stored.
    func submit(taxId: String) async throws -> OnboardingSubmitResponse {
        try await api.post("/v1/onboarding/submit", body: OnboardingSubmitRequest(taxId: taxId))
    }

    /// Get current onboarding state + all saved data (for resume).
    func getStatus() async throws -> OnboardingStatusResponse {
        try await api.get("/v1/onboarding/status")
    }
}
