import SwiftUI

struct SocialButtonsView: View {
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
