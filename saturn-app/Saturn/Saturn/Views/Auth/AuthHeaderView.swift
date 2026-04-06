import SwiftUI

struct AuthHeaderView: View {
    let scale: CGFloat
    let onBack: () -> Void

    var body: some View {
        ZStack {
            Button(action: onBack) {
                Label(L10n.General.back, systemImage: "chevron.left")
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeText)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .contentShape(Rectangle())
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Image("logo_white")
                .resizable()
                .scaledToFit()
                .frame(height: 36 * scale)
                .accessibilityLabel(L10n.General.appName)
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 8 * scale)
    }
}
