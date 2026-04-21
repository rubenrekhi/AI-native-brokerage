import SwiftUI

struct SubmitButtonView: View {
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
