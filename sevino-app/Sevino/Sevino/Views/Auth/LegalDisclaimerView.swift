import SwiftUI

struct LegalDisclaimerView: View {
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
