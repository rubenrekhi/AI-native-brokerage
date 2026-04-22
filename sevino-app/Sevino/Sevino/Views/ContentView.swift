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

    @ViewBuilder
    private var authenticatedView: some View {
        switch viewModel.route {
        case .idle, .loading:
            loadingView
        case .statusCheckFailed:
            StatusCheckRetryView(onRetry: checkStatus)
        case .phone:
            PhoneNumberView(onComplete: savePhoneNumber)
                .alert(
                    L10n.General.errorTitle,
                    isPresented: phoneErrorPresented,
                    presenting: viewModel.error
                ) { _ in
                    Button(L10n.General.ok) { viewModel.clearError() }
                } message: { error in
                    Text(error)
                }
        case .onboarding(let step, let data):
            OnboardingContainerView(
                initialStep: step,
                resumeData: data,
                onComplete: viewModel.completeOnboarding,
                onLogOut: signOut
            )
            .alert(
                L10n.General.errorTitle,
                isPresented: signOutErrorPresented,
                presenting: authVM.authError
            ) { _ in
                Button(L10n.General.ok) { authVM.clearError() }
            } message: { error in
                Text(error)
            }
        case .alpacaSetup(let step, let userName, let data):
            AlpacaSetupContainerView(
                userName: userName,
                initialStep: step,
                resumeData: data,
                onComplete: viewModel.completeAlpacaSetup
            )
        case .home:
            HomeView()
        }
    }

    private var phoneErrorPresented: Binding<Bool> {
        Binding(
            get: { viewModel.showPhoneError },
            set: { if !$0 { viewModel.clearError() } }
        )
    }

    private var signOutErrorPresented: Binding<Bool> {
        Binding(
            get: { authVM.authError != nil },
            set: { if !$0 { authVM.clearError() } }
        )
    }

    private var loadingView: some View {
        ZStack {
            OnboardingBackgroundView()
            Image("logo_white")
                .resizable()
                .scaledToFit()
                .frame(height: 40)
                .accessibilityHidden(true)
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
            checkStatus()
        }
    }

    private func checkStatus() {
        Task { await viewModel.checkOnboardingStatus() }
    }

    private func savePhoneNumber(_ phoneNumber: String) {
        Task { await viewModel.savePhoneNumber(phoneNumber) }
    }

    private func signOut() {
        Task { await authVM.signOut() }
    }
}

// MARK: - Status check retry

private struct StatusCheckRetryView: View {
    let onRetry: () -> Void

    var body: some View {
        ZStack {
            OnboardingBackgroundView()
            VStack(spacing: 16) {
                Text(L10n.General.connectionErrorTitle)
                    .font(.dmSerif(size: 28))
                    .foregroundStyle(Color.welcomeText)
                    .multilineTextAlignment(.center)

                Text(L10n.General.connectionErrorBody)
                    .font(.system(size: 15))
                    .foregroundStyle(Color.welcomeText.opacity(0.8))
                    .multilineTextAlignment(.center)

                Button(action: onRetry) {
                    Text(L10n.General.tryAgain)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Color.welcomeButtonDarkTint)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                }
                .buttonStyle(.plain)
                .modifier(SevinoGlass.tintedButton(tint: Color.welcomeButtonLightTint.opacity(0.4)))
                .padding(.top, 8)
            }
            .padding(.horizontal, 32)
        }
        .preferredColorScheme(.dark)
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
        viewModel: ContentViewModel()
    )
}

#Preview("Status Check Retry") {
    StatusCheckRetryView(onRetry: {})
}
