import SwiftUI

struct HomeGreetingSection: View {
    @Environment(\.colorScheme) private var colorScheme
    let scale: CGFloat
    let greeting: String
    @Binding var showExplore: Bool
    let isHidden: Bool

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

            if showExplore && !isHidden {
                HStack(spacing: 8 * scale) {
                    Button(L10n.Home.exploreButton, action: {})
                        .font(.system(size: 15 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Button(L10n.Home.dismissExploreAccessibility, systemImage: "xmark", action: dismissExplore)
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

    private func dismissExplore() {
        withAnimation { showExplore = false }
    }
}
