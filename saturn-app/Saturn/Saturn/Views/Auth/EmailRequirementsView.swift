import SwiftUI

struct EmailRequirementsView: View {
    let email: String
    let scale: CGFloat

    static func hasValidDomain(_ email: String) -> Bool {
        let parts = email.split(separator: "@", maxSplits: 1)
        guard parts.count == 2 else { return false }
        let domain = parts[1]
        return domain.contains(".") && !domain.hasPrefix(".") && !domain.hasSuffix(".")
    }

    var body: some View {
        HStack(spacing: 0) {
            RequirementTagView(label: L10n.Auth.reqContainsAt, met: email.contains("@"), scale: scale)
            Spacer(minLength: 0)
            RequirementTagView(label: L10n.Auth.reqValidDomain, met: Self.hasValidDomain(email), scale: scale)
            Spacer(minLength: 0)
            RequirementTagView(label: L10n.Auth.reqNoSpaces, met: !email.contains(" "), scale: scale)
        }
        .padding(.top, 4 * scale)
        .animation(.easeInOut(duration: 0.2), value: email)
    }
}
