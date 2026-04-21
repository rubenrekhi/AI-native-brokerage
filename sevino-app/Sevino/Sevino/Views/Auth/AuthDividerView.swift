import SwiftUI

struct AuthDividerView: View {
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
