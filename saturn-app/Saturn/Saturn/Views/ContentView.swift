import SwiftUI

struct ContentView: View {
    @State private var authVM: AuthViewModel
    @State private var authRoute: AuthRoute = .welcome
    @State private var showPhoneSheet = false
    @State private var showOnboarding = false
    @State private var showAlpacaSetup = false
    @State private var onboardingUserName = ""
    private let onboardingService: any OnboardingServiceProtocol = OnboardingService.shared
    @State private var isCheckingStatus = false
    @State private var onboardingResumeStep: Int = 1
    @State private var onboardingResumeData: OnboardingResumeManager.OnboardingResumeData?
    @State private var alpacaResumeStep: Int = 1
    @State private var alpacaResumeData: OnboardingResumeManager.AlpacaResumeData?

    private enum AuthRoute {
        case welcome, signIn, signUp
    }

    init(authVM: AuthViewModel = AuthViewModel()) {
        self._authVM = State(initialValue: authVM)
    }

    var body: some View {
        Group {
            if authVM.isAuthenticated {
                authenticatedView
            } else {
                unauthenticatedView
            }
        }
        .onChange(of: authVM.isAuthenticated) { _, isAuthenticated in
            if isAuthenticated && authRoute == .signUp {
                // Fresh signup — go straight to phone → onboarding, no status check
                showPhoneSheet = true
                showOnboarding = true
            } else if isAuthenticated {
                // Returning user — either login or cold launch session restore
                checkOnboardingStatus()
            }
        }
        .task {
            // Cold launch with existing session — check immediately if already authenticated
            if authVM.isAuthenticated {
                checkOnboardingStatus()
            }
        }
    }

    private var authenticatedView: some View {
        Group {
            if isCheckingStatus {
                loadingView
            } else if showPhoneSheet {
                PhoneNumberView { phoneNumber in
                    savePhoneNumber(phoneNumber)
                }
            } else if showOnboarding {
                OnboardingContainerView(
                    initialStep: onboardingResumeData != nil ? onboardingResumeStep : 1,
                    resumeData: onboardingResumeData
                ) { name in
                    onboardingUserName = name
                    showOnboarding = false
                    showAlpacaSetup = true
                    // Reset resume data so Alpaca setup starts fresh from onboarding completion
                    alpacaResumeStep = 1
                    alpacaResumeData = nil
                }
            } else if showAlpacaSetup {
                AlpacaSetupContainerView(
                    userName: onboardingUserName,
                    initialStep: alpacaResumeData != nil ? alpacaResumeStep : 1,
                    resumeData: alpacaResumeData,
                    onComplete: {
                        showAlpacaSetup = false
                    }
                )
            } else {
                HomeView()
            }
        }
    }

    private var loadingView: some View {
        ZStack {
            OnboardingBackgroundView()
            Image("logo_white")
                .resizable()
                .scaledToFit()
                .frame(height: 40)
        }
        .preferredColorScheme(.dark)
    }

    @ViewBuilder
    private var unauthenticatedView: some View {
        switch authRoute {
        case .welcome:
            WelcomeView(
                onLogIn: { authRoute = .signIn },
                onSignUp: { authRoute = .signUp }
            )
        case .signIn:
            AuthView(isSignUp: false, onBack: { authRoute = .welcome }, authVM: authVM)
        case .signUp:
            AuthView(isSignUp: true, onBack: { authRoute = .welcome }, authVM: authVM)
        }
    }

    private func savePhoneNumber(_ phoneNumber: String) {
        Task {
            do {
                try await onboardingService.saveStep(
                    OnboardingPatchRequest(step: "welcome", phoneNumber: phoneNumber)
                )
            } catch {
                print("[ContentView] Failed to save phone: \(error)")
            }
        }
        showPhoneSheet = false
    }

    private func checkOnboardingStatus() {
        isCheckingStatus = true
        Task {
            do {
                let status = try await onboardingService.getStatus()
                let destination = OnboardingResumeManager.destination(from: status)

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
            } catch {
                // If status check fails, show home — don't block the user
                print("[ContentView] Status check failed: \(error)")
            }
            isCheckingStatus = false
        }
    }

    private func signOut() {
        Task {
            await authVM.signOut()
            authRoute = .welcome
            showPhoneSheet = false
            showOnboarding = false
            showAlpacaSetup = false
            onboardingResumeData = nil
            alpacaResumeData = nil
        }
    }
}

// MARK: - Previews

@Observable
private final class PreviewAuthService: AuthServiceProtocol {
    var isAuthenticated: Bool

    init(isAuthenticated: Bool = false) {
        self.isAuthenticated = isAuthenticated
    }

    func signUp(email: String, password: String) async throws {}
    func signIn(email: String, password: String) async throws { isAuthenticated = true }
    func signOut() async throws { isAuthenticated = false }
}

#Preview("Logged Out") {
    ContentView()
}

#Preview("Logged In") {
    ContentView(authVM: AuthViewModel(authService: PreviewAuthService(isAuthenticated: true)))
}
