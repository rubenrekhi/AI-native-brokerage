import SwiftUI

struct AuthView: View {
    let isSignUp: Bool
    let onBack: () -> Void
    let authVM: AuthViewModel

    @State private var email = ""
    @State private var password = ""
    @State private var scale: CGFloat = 1

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                AuthHeaderView(scale: scale, onBack: onBack)

                ScrollView {
                    VStack(spacing: 0) {
                        AuthTitleView(isSignUp: isSignUp, scale: scale)
                        SocialButtonsView(
                            scale: scale,
                            onGoogle: signInWithGoogle,
                            onApple: signInWithApple
                        )
                        AuthDividerView(scale: scale)
                        EmailSectionView(
                            isSignUp: isSignUp,
                            scale: scale,
                            email: $email
                        )
                        PasswordSectionView(
                            isSignUp: isSignUp,
                            scale: scale,
                            password: $password
                        )

                        if let error = authVM.authError {
                            Text(error)
                                .font(.system(size: 13 * scale))
                                .foregroundStyle(Color.sevinoNegative)
                                .multilineTextAlignment(.center)
                                .padding(.top, 12 * scale)
                                .padding(.horizontal, 24 * scale)
                        }

                        SubmitButtonView(
                            isSignUp: isSignUp,
                            isLoading: authVM.isLoading,
                            isFormIncomplete: isFormIncomplete,
                            scale: scale,
                            action: submit
                        )
                    }
                }
                .scrollIndicators(.hidden)

                Spacer(minLength: 0)

                if isSignUp {
                    LegalDisclaimerView(scale: scale)
                }
            }
        }
        .background { AuthBackgroundView() }
        .preferredColorScheme(.dark)
        .onAppear { authVM.clearError() }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
    }

    private func signInWithGoogle() {}

    private func signInWithApple() {}

    private var isEmailValid: Bool {
        email.contains("@") && EmailRequirementsView.hasValidDomain(email) && !email.contains(" ")
    }

    private var isPasswordValid: Bool {
        password.contains(where: \.isUppercase) &&
        password.contains(where: \.isLowercase) &&
        password.contains(where: \.isNumber) &&
        (8...64).contains(password.count) &&
        password.contains { !$0.isLetter && !$0.isNumber && !$0.isWhitespace } &&
        !password.contains(" ")
    }

    private var isFormIncomplete: Bool {
        if isSignUp {
            return !isEmailValid || !isPasswordValid
        }
        return email.isEmpty || password.isEmpty
    }

    private func submit() {
        Task {
            if isSignUp {
                await authVM.signUp(email: email, password: password)
            } else {
                await authVM.signIn(email: email, password: password)
            }
        }
    }
}

// MARK: - Previews

#Preview("Sign Up") {
    AuthView(isSignUp: true, onBack: {}, authVM: AuthViewModel())
}

#Preview("Sign In") {
    AuthView(isSignUp: false, onBack: {}, authVM: AuthViewModel())
}
