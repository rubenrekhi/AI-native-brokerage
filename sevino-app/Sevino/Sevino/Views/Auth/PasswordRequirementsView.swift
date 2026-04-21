import SwiftUI

struct PasswordRequirementsView: View {
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
