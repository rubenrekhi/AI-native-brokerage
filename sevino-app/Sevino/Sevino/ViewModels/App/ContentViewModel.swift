import Foundation

/// Drives the root view routing between phone capture, onboarding, Alpaca setup, and home.
/// Owns the onboarding status check and related resume data so the view stays declarative.
@Observable
final class ContentViewModel {
    private let onboardingService: any OnboardingServiceProtocol

    // MARK: - Routing

    private(set) var route: AuthenticatedRoute = .idle

    // MARK: - Transient UI state

    private(set) var isLoading = false
    private(set) var showPhoneError = false

    // MARK: - Error

    private(set) var error: String?

    // MARK: - Init

    init(onboardingService: any OnboardingServiceProtocol = OnboardingService.shared) {
        self.onboardingService = onboardingService
    }

    // MARK: - Auth transitions

    /// Fresh signup: skip the status check and go straight to phone capture.
    /// There is no server-side status to resume from on a brand new account, so
    /// the onboarding flow starts once the phone number is saved.
    func startFreshSignUpFlow() {
        route = .phone
    }

    // MARK: - Flow completion

    func completeOnboarding(userName: String) {
        route = .alpacaSetup(step: 1, userName: userName, data: nil)
    }

    func completeAlpacaSetup() {
        route = .home
    }

    // MARK: - Async operations

    /// Saves the phone number and advances to onboarding on success. On failure, the
    /// route stays on `.phone` and `error` is set so the view can surface an alert
    /// and allow a retry.
    func savePhoneNumber(_ phoneNumber: String) async {
        error = nil
        showPhoneError = false
        isLoading = true
        defer { isLoading = false }
        do {
            try await onboardingService.saveStep(
                OnboardingPatchRequest(step: "welcome", phoneNumber: phoneNumber)
            )
            route = .onboarding(step: 1, data: nil)
        } catch let caughtError {
            error = caughtError.localizedDescription
            showPhoneError = true
        }
    }

    /// Fetches onboarding status and routes to the matching destination. On failure,
    /// routes to `.statusCheckFailed` so the view shows a retry prompt instead of
    /// silently falling through to home.
    func checkOnboardingStatus() async {
        error = nil
        route = .loading
        do {
            let status = try await onboardingService.getStatus()
            apply(OnboardingResumeManager.destination(from: status))
        } catch let caughtError {
            error = caughtError.localizedDescription
            route = .statusCheckFailed
        }
    }

    func clearError() {
        error = nil
        showPhoneError = false
    }

    // MARK: - Helpers

    private func apply(_ destination: OnboardingResumeManager.Destination) {
        switch destination {
        case .home:
            route = .home
        case .onboarding(let step, let data):
            route = .onboarding(step: step, data: data)
        case .alpacaSetup(let step, let data):
            route = .alpacaSetup(step: step, userName: data.userName, data: data)
        case .loading:
            break
        }
    }
}
