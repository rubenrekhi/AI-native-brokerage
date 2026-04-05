import SwiftUI

struct AuthView: View {
    @Bindable var authVM: AuthViewModel

    @State private var email = ""
    @State private var password = ""
    @State private var isSignUp: Bool

    init(authVM: AuthViewModel, isSignUp: Bool = false) {
        self.authVM = authVM
        self._isSignUp = State(initialValue: isSignUp)
    }

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            // App branding
            Text(L10n.General.appName)
                .font(.largeTitle.bold())

            // Form fields
            VStack(spacing: 12) {
                TextField(L10n.Auth.emailPlaceholder, text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .padding()
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                SecureField(L10n.Auth.passwordPlaceholder, text: $password)
                    .textContentType(isSignUp ? .newPassword : .password)
                    .padding()
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            // Error message
            if let error = authVM.authError {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            // Email confirmation message
            if authVM.requiresEmailConfirmation {
                Text(L10n.Auth.emailConfirmation)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            // Primary action button
            Button {
                Task {
                    if isSignUp {
                        await authVM.signUp(email: email, password: password)
                    } else {
                        await authVM.signIn(email: email, password: password)
                    }
                }
            } label: {
                if authVM.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                } else {
                    Text(isSignUp ? L10n.Auth.signUp : L10n.Auth.signIn)
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(email.isEmpty || password.isEmpty || authVM.isLoading)

            // Toggle between sign in / sign up
            Button {
                isSignUp.toggle()
                authVM.authError = nil
            } label: {
                Text(isSignUp ? L10n.Auth.switchToSignIn : L10n.Auth.switchToSignUp)
                    .font(.footnote)
            }

            Spacer()
        }
        .padding(.horizontal, 32)
    }
}

#Preview {
    AuthView(authVM: AuthViewModel())
}
