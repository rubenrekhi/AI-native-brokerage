import SwiftUI

struct ContentView: View {
    @State private var authVM: AuthViewModel
    @State private var authRoute: AuthRoute = .welcome
    @State private var showPhoneSheet = false
    @State private var showOnboarding = false
    @State private var showAlpacaSetup = false
    @State private var onboardingUserName = ""

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
                showPhoneSheet = true
                showOnboarding = true
            }
        }
    }

    private var authenticatedView: some View {
        Group {
            if showPhoneSheet {
                PhoneNumberView(onComplete: { showPhoneSheet = false })
            } else if showOnboarding {
                OnboardingContainerView { name in
                    onboardingUserName = name
                    showOnboarding = false
                    showAlpacaSetup = true
                }
            } else if showAlpacaSetup {
                AlpacaSetupContainerView(
                    userName: onboardingUserName,
                    onComplete: { showAlpacaSetup = false }
                )
            } else {
                HomeView()
            }
        }
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

    private func signOut() {
        Task {
            await authVM.signOut()
            authRoute = .welcome
            showPhoneSheet = false
            showOnboarding = false
            showAlpacaSetup = false
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
