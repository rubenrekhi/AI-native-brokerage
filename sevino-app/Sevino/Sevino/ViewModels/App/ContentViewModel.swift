import Foundation

/// Drives the root view routing between phone capture, onboarding, Alpaca setup, and home.
/// Owns the onboarding status check and related resume data so the view stays declarative.
@Observable
final class ContentViewModel {
    private let onboardingService: any OnboardingServiceProtocol
    private let authService: any AuthServiceProtocol

    // MARK: - Routing flags

    private(set) var isCheckingStatus = false
    private(set) var isLoading = false
    private(set) var showPhoneSheet = false
    private(set) var showOnboarding = false
    private(set) var showAlpacaSetup = false

    // MARK: - Resume data

    private(set) var onboardingUserName = ""
    private(set) var onboardingResumeStep = 1
    private(set) var onboardingResumeData: OnboardingResumeManager.OnboardingResumeData?
    private(set) var alpacaResumeStep = 1
    private(set) var alpacaResumeData: OnboardingResumeManager.AlpacaResumeData?

    // MARK: - Error
    // Set on failure but not yet bound to UI — surfacing is handled by ticket SEV-237.
    private(set) var error: String?

    // MARK: - Init

    init(
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        authService: any AuthServiceProtocol = AuthService.shared
    ) {
        self.onboardingService = onboardingService
        self.authService = authService
    }

    // MARK: - Auth transitions

    /// Fresh signup: skip the status check and go straight to phone capture → onboarding.
    func startFreshSignUpFlow() {
        showPhoneSheet = true
        showOnboarding = true
    }

    // MARK: - Flow completion

    func completeOnboarding(userName: String) {
        onboardingUserName = userName
        showOnboarding = false
        showAlpacaSetup = true
        alpacaResumeStep = 1
        alpacaResumeData = nil
    }

    func completeAlpacaSetup() {
        showAlpacaSetup = false
    }

    // MARK: - Async operations

    /// Saves the phone number, then dismisses the sheet. On failure, records the error
    /// but still dismisses so the user isn't blocked — data can be re-sent on resume.
    /// Error surfacing in the UI is handled by ticket SEV-237.
    func savePhoneNumber(_ phoneNumber: String) async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            try await onboardingService.saveStep(
                OnboardingPatchRequest(step: "welcome", phoneNumber: phoneNumber)
            )
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
        showPhoneSheet = false
    }

    func checkOnboardingStatus() async {
        error = nil
        isCheckingStatus = true
        defer { isCheckingStatus = false }
        do {
            let status = try await onboardingService.getStatus()
            apply(OnboardingResumeManager.destination(from: status))
        } catch let caughtError {
            // Status check failures fall through to home so the user isn't blocked.
            error = caughtError.localizedDescription
        }
    }

    func signOut() async {
        error = nil
        do {
            try await authService.signOut()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
        resetRoutingState()
    }

    // MARK: - Helpers

    private func apply(_ destination: OnboardingResumeManager.Destination) {
        switch destination {
        case .home:
            showOnboarding = false
            showAlpacaSetup = false
        case .onboarding(let step, let data):
            onboardingResumeStep = step
            onboardingResumeData = data
            onboardingUserName = data.userName
            showOnboarding = true
        case .alpacaSetup(let step, let data):
            alpacaResumeStep = step
            alpacaResumeData = data
            onboardingUserName = data.userName
            showAlpacaSetup = true
        case .loading:
            break
        }
    }

    private func resetRoutingState() {
        showPhoneSheet = false
        showOnboarding = false
        showAlpacaSetup = false
        onboardingResumeData = nil
        alpacaResumeData = nil
    }
}
