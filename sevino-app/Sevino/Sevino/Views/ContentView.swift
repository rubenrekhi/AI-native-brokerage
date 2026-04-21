import SwiftUI

struct ContentView: View {
    @State private var authVM: AuthViewModel
    @State private var viewModel: ContentViewModel
    @State private var authRoute: AuthRoute = .welcome

    private enum AuthRoute {
        case welcome, signIn, signUp
    }

    init(
        authVM: AuthViewModel = AuthViewModel(),
        viewModel: ContentViewModel = ContentViewModel()
    ) {
        self._authVM = State(initialValue: authVM)
        self._viewModel = State(initialValue: viewModel)
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
            handleAuthChange(isAuthenticated: isAuthenticated)
        }
        .task {
            if authVM.isAuthenticated {
                await viewModel.checkOnboardingStatus()
            }
        }
    }

    private var authenticatedView: some View {
        Group {
            if viewModel.isCheckingStatus {
                loadingView
            } else if viewModel.showPhoneSheet {
                PhoneNumberView(onComplete: savePhoneNumber)
            } else if viewModel.showOnboarding {
                OnboardingContainerView(
                    initialStep: viewModel.onboardingResumeData != nil ? viewModel.onboardingResumeStep : 1,
                    resumeData: viewModel.onboardingResumeData,
                    onComplete: viewModel.completeOnboarding
                )
            } else if viewModel.showAlpacaSetup {
                AlpacaSetupContainerView(
                    userName: viewModel.onboardingUserName,
                    initialStep: viewModel.alpacaResumeData != nil ? viewModel.alpacaResumeStep : 1,
                    resumeData: viewModel.alpacaResumeData,
                    onComplete: viewModel.completeAlpacaSetup
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

    private func handleAuthChange(isAuthenticated: Bool) {
        guard isAuthenticated else {
            // Reset the local auth route so a signed-out user always lands on welcome.
            authRoute = .welcome
            return
        }
        if authRoute == .signUp {
            // Fresh signup — go straight to phone → onboarding, no status check
            viewModel.startFreshSignUpFlow()
        } else {
            // Returning user — either login or cold launch session restore
            Task { await viewModel.checkOnboardingStatus() }
        }
    }

    private func savePhoneNumber(_ phoneNumber: String) {
        Task { await viewModel.savePhoneNumber(phoneNumber) }
    }
}

// MARK: - Previews

@Observable
private final class PreviewAuthService: AuthServiceProtocol {
    var isAuthenticated: Bool
    var accessToken: String? { nil }

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
    let authService = PreviewAuthService(isAuthenticated: true)
    return ContentView(
        authVM: AuthViewModel(authService: authService),
        viewModel: ContentViewModel(authService: authService)
    )
}
