import SwiftUI

struct EmailSectionView: View {
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
