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
        case .phoneVerification(let phoneNumber):
            PhoneVerificationView(
                phoneNumber: phoneNumber,
                onVerified: viewModel.onPhoneVerified,
                onChangeNumber: viewModel.onChangeNumber
            )
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
        LoadingLogoView()
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
            // Skip status check — a brand-new account has no server state to resume from.
            viewModel.startFreshSignUpFlow()
        } else {
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

// MARK: - Loading logo

private struct LoadingLogoView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isBreathing = false

    var body: some View {
        ZStack {
            OnboardingBackgroundView()
            GeometryReader { proxy in
                let scale = proxy.size.width / 393
                Image("logo_white")
                    .resizable()
                    .scaledToFit()
                    .frame(height: 40 * scale)
                    .scaleEffect(isBreathing ? 1.06 : 0.96)
                    .opacity(isBreathing ? 1.0 : 0.7)
                    .accessibilityHidden(true)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .preferredColorScheme(.dark)
        .task { startBreathingAnimation() }
    }

    private func startBreathingAnimation() {
        guard !reduceMotion else { return }
        withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) {
            isBreathing = true
        }
    }
}

// MARK: - Status check retry

private struct StatusCheckRetryView: View {
    let onRetry: () -> Void

    var body: some View {
        ZStack {
            OnboardingBackgroundView()
            GeometryReader { proxy in
                let scale = proxy.size.width / 393
                SevinoGlassContainer {
                    VStack(spacing: 16 * scale) {
                        Image(systemName: "wifi.exclamationmark")
                            .font(.system(size: 26 * scale, weight: .light))
                            .foregroundStyle(Color.welcomeText)
                            .accessibilityHidden(true)

                        VStack(spacing: 6 * scale) {
                            Text(L10n.General.connectionErrorTitle)
                                .font(.system(size: 22 * scale, weight: .semibold))
                                .foregroundStyle(Color.welcomeText)
                                .multilineTextAlignment(.center)

                            Text(L10n.General.connectionErrorBody)
                                .font(.system(size: 11 * scale))
                                .foregroundStyle(Color.welcomeText.opacity(0.8))
                                .multilineTextAlignment(.center)
                        }

                        Button(action: onRetry) {
                            Text(L10n.General.tryAgain)
                                .font(.system(size: 12 * scale, weight: .semibold))
                                .foregroundStyle(Color.welcomeButtonDarkTint)
                                .padding(.horizontal, 20 * scale)
                                .padding(.vertical, 8 * scale)
                                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
                        }
                        .buttonStyle(.plain)
                        .modifier(SevinoGlass.tintedButton(tint: Color.welcomeButtonLightTint.opacity(0.4)))
                        .padding(.top, 2 * scale)
                    }
                    .padding(.horizontal, 22 * scale)
                    .padding(.vertical, 26 * scale)
                    .frame(maxWidth: .infinity)
                    .modifier(SevinoGlass.card)
                }
                .padding(.horizontal, 72 * scale)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .preferredColorScheme(.dark)
    }
}

// MARK: - Previews

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

#Preview("Loading Logo") {
    LoadingLogoView()
}
