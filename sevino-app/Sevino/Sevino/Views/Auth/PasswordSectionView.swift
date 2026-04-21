import SwiftUI

struct PasswordSectionView: View {
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
