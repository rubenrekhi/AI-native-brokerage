import SwiftUI

struct ContentView: View {
    @State private var authVM: AuthViewModel
    @State private var authRoute: AuthRoute = .welcome

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
    }

    private var authenticatedView: some View {
        // ROUTE TO HOME PAGE HERE
        VStack {
            Text(L10n.General.appName)
                .font(.largeTitle.bold())
            Button(L10n.Auth.signOut, action: signOut)
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
            AuthView(authVM: authVM, isSignUp: false)
        case .signUp:
            AuthView(authVM: authVM, isSignUp: true)
        }
    }

    private func signOut() {
        Task {
            await authVM.signOut()
            authRoute = .welcome
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
