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
        if authVM.isAuthenticated {
            // ROUTE TO HOME PAGE HERE
            VStack {
                Text(L10n.General.appName)
                    .font(.largeTitle.bold())
                Button(L10n.Auth.signOut) {
                    Task {
                        await authVM.signOut()
                        authRoute = .welcome
                    }
                }
            }
        } else {
            switch authRoute {
            case .welcome:
                WelcomeView(
                    onLogIn: { authRoute = .signIn },
                    onSignUp: { authRoute = .signUp }
                )
            // Change these cases to be SignUpView / SignInView when real views are created
            case .signIn:
                AuthView(authVM: authVM, isSignUp: false)
            case .signUp:
                AuthView(authVM: authVM, isSignUp: true)
            }
        }
    }
}

#Preview("Logged Out") {
    ContentView()
}

#Preview("Logged In") {
    ContentView()
}
