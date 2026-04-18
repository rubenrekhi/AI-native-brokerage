import SwiftUI

struct AuthView: View {
    let isSignUp: Bool
    let onBack: () -> Void

    @Bindable var authVM: AuthViewModel
    @State private var email = ""
    @State private var password = ""
    @State private var scale: CGFloat = 1

    var body: some View {
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

    // MARK: - Actions

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

// MARK: - Auth Title

private struct AuthTitleView: View {
    let isSignUp: Bool
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 12 * scale) {
            Text(isSignUp ? L10n.Auth.signUpTitle : L10n.Auth.signInTitle)
                .font(.dmSerif(size: 34 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)

            Text(isSignUp ? L10n.Auth.signUpSubtitle : L10n.Auth.signInSubtitle)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 24 * scale)
        .padding(.horizontal, 24 * scale)
    }
}

// MARK: - Social Buttons

private struct SocialButtonsView: View {
    let scale: CGFloat
    let onGoogle: () -> Void
    let onApple: () -> Void

    var body: some View {
        VStack(spacing: 16 * scale) {
            Button(action: onGoogle) {
                HStack(spacing: 10 * scale) {
                    Image("google_logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 20 * scale, height: 20 * scale)
                        .accessibilityHidden(true)
                    Text(L10n.Auth.continueWithGoogle)
                        .font(.system(size: 16 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeButtonDarkTint)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
            }
            .buttonStyle(.plain)
            .modifier(SevinoGlass.tintedButton(tint: Color.welcomeButtonLightTint.opacity(0.4)))

            Button(action: onApple) {
                HStack(spacing: 10 * scale) {
                    Image(systemName: "apple.logo")
                        .font(.system(size: 18 * scale))
                        .foregroundStyle(Color.welcomeText)
                        .accessibilityHidden(true)
                    Text(L10n.Auth.continueWithApple)
                        .font(.system(size: 16 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
            }
            .buttonStyle(.plain)
            .modifier(SevinoGlass.tintedButton(tint: .welcomeButtonDarkTint))
        }
        .padding(.top, 24 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Divider

private struct AuthDividerView: View {
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 16 * scale) {
            Rectangle()
                .fill(Color.welcomeText)
                .frame(height: 0.5)
            Text(L10n.Auth.orDivider)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.welcomeText)
            Rectangle()
                .fill(Color.welcomeText)
                .frame(height: 0.5)
        }
        .padding(.top, 20 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Email Section

private struct EmailSectionView: View {
    let isSignUp: Bool
    let scale: CGFloat
    @Binding var email: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(L10n.Auth.emailPlaceholder)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)

            TextField("", text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.welcomeText)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.card)

            if isSignUp && !email.isEmpty {
                EmailRequirementsView(email: email, scale: scale)
            }
        }
        .padding(.top, 16 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Password Section

private struct PasswordSectionView: View {
    let isSignUp: Bool
    let scale: CGFloat
    @Binding var password: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(L10n.Auth.passwordPlaceholder)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)

            SecureField("", text: $password)
                .textContentType(isSignUp ? .newPassword : .password)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.welcomeText)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.card)

            if isSignUp && !password.isEmpty {
                PasswordRequirementsView(password: password, scale: scale)
            }
        }
        .padding(.top, 12 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Password Requirements

private struct PasswordRequirementsView: View {
    let password: String
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            HStack(spacing: 0) {
                RequirementTagView(label: L10n.Auth.reqUppercase, met: password.contains(where: \.isUppercase), scale: scale)
                Spacer(minLength: 0)
                RequirementTagView(label: L10n.Auth.reqLowercase, met: password.contains(where: \.isLowercase), scale: scale)
                Spacer(minLength: 0)
                RequirementTagView(label: L10n.Auth.reqNumber, met: password.contains(where: \.isNumber), scale: scale)
            }
            HStack(spacing: 0) {
                RequirementTagView(label: L10n.Auth.reqLength, met: (8...64).contains(password.count), scale: scale)
                Spacer(minLength: 0)
                RequirementTagView(label: L10n.Auth.reqSpecialChar, met: password.contains { !$0.isLetter && !$0.isNumber && !$0.isWhitespace }, scale: scale)
                Spacer(minLength: 0)
                RequirementTagView(label: L10n.Auth.reqNoSpaces, met: !password.contains(" "), scale: scale)
            }
        }
        .padding(.top, 4 * scale)
        .animation(.easeInOut(duration: 0.2), value: password)
    }
}

// MARK: - Submit Button

private struct SubmitButtonView: View {
    let isSignUp: Bool
    let isLoading: Bool
    let isFormIncomplete: Bool
    let scale: CGFloat
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if isLoading {
                    ProgressView()
                        .tint(Color.welcomeText)
                } else {
                    Text(isSignUp ? L10n.Auth.signUp : L10n.Auth.signIn)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(tint: .welcomeButtonDarkTint))
        .disabled(isFormIncomplete || isLoading)
        .opacity((isFormIncomplete && !isLoading) ? 0.6 : 1)
        .padding(.top, 20 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Legal Disclaimer

private struct LegalDisclaimerView: View {
    let scale: CGFloat

    var body: some View {
        Text(L10n.Auth.legalDisclaimer)
            .font(.system(size: 12 * scale))
            .foregroundStyle(Color.welcomeTextMuted)
            .tint(Color.welcomeTextSecondary)
            .multilineTextAlignment(.center)
            .lineSpacing(2 * scale)
            .padding(.horizontal, 24 * scale)
            .padding(.bottom, 16 * scale)
    }
}

// MARK: - Previews

#Preview("Sign Up") {
    AuthView(isSignUp: true, onBack: {}, authVM: AuthViewModel())
}

#Preview("Sign In") {
    AuthView(isSignUp: false, onBack: {}, authVM: AuthViewModel())
}
