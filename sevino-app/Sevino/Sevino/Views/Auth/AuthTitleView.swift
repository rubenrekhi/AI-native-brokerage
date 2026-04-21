import SwiftUI

struct AuthTitleView: View {
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
