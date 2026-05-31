import SwiftUI

struct HomeGreetingSection: View {
    @Environment(\.colorScheme) private var colorScheme
    let scale: CGFloat
    let greeting: String
    let isHidden: Bool
    let digestAvailable: Bool
    let onTapDigest: () -> Void
    @Binding var showDailyDigestPrompt: Bool

    var body: some View {
        VStack(spacing: 16 * scale) {
            Image(colorScheme == .dark ? "logo_white" : "logo_black")
                .resizable()
                .scaledToFit()
                .frame(height: 40 * scale)
                .accessibilityLabel(L10n.General.appName)

            Text(greeting)
                .font(.system(size: 28 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)

            if showDailyDigestPrompt && !isHidden && digestAvailable {
                HStack(spacing: 8 * scale) {
                    Button(action: onTapDigest) {
                        HStack(spacing: 6 * scale) {
                            Image(systemName: "cup.and.saucer.fill")
                                .font(.system(size: 13 * scale))
                            Text(L10n.Home.dailyDigestButton)
                                .font(.system(size: 15 * scale))
                        }
                    }
                    .foregroundStyle(Color.sevinoSecondary)

                    Button(L10n.Home.dismissDailyDigestAccessibility, systemImage: "xmark", action: dismissPrompt)
                        .labelStyle(.iconOnly)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 10 * scale)
                .modifier(SevinoGlass.chip)
            }
        }
    }

    private func dismissPrompt() {
        withAnimation { showDailyDigestPrompt = false }
    }
}
