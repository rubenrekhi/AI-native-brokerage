import SwiftUI

struct ContentView: View {
    @Environment(\.colorScheme) private var colorScheme
    @State private var authVM: AuthViewModel

    private let themeColors: [(name: String, color: Color, lightHex: String, darkHex: String)] = [
        ("primary", .saturnPrimary, "#F9F8F6", "#000000"),
        ("secondary", .saturnSecondary, "#121111", "#F9F8F6"),
        ("accent", .saturnAccent, "#CCBEFF", "#29243B"),
        ("grey-contrast", .saturnGreyContrast, "#1E1E1E", "#ABABAB"),
        ("grey-accent", .saturnGreyAccent, "#BFBFBF", "#312E2E"),
        ("settings-bg", .saturnSettingsBg, "#F5F4ED", "#040404"),
        ("settings-contrast", .saturnSettingsContrast, "#FFFFFF", "#121111"),
        ("positive", .saturnPositive, "#1E8A60", "#1E8A60"),
        ("negative", .saturnNegative, "#991C1E", "#991C1E"),
        ("highlight-bg", .saturnHighlightBg, "#C9DAF0", "#C9DAF0"),
        ("highlight-text", .saturnHighlightText, "#0088FF", "#0088FF"),
    ]

    init(authVM: AuthViewModel = AuthViewModel()) {
        self._authVM = State(initialValue: authVM)
    }

    var body: some View {
        Group {
            if authVM.isAuthenticated {
                NavigationStack {
                    designSystemShowcase
                        .navigationTitle(L10n.General.appName)
                        .navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .topBarTrailing) {
                                Button(L10n.Auth.signOut) {
                                    Task { await authVM.signOut() }
                                }
                            }
                        }
                }
            } else {
                AuthView(authVM: authVM)
            }
        }
    }

    @ViewBuilder
    private var designSystemShowcase: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Colour Palette")
                    .font(.largeTitle.bold())
                    .foregroundStyle(Color.saturnSecondary)

                Text(colorScheme == .dark ? "Dark Mode" : "Light Mode")
                    .font(.headline)
                    .foregroundStyle(Color.saturnGreyContrast)

                LazyVGrid(
                    columns: [GridItem(.flexible()), GridItem(.flexible())],
                    spacing: 12
                ) {
                    ForEach(themeColors, id: \.name) { item in
                        colorSwatch(item)
                    }
                }

                Divider()
                    .padding(.vertical, 8)

                Text("Font Family")
                    .font(.largeTitle.bold())
                    .foregroundStyle(Color.saturnSecondary)

                VStack(alignment: .leading, spacing: 16) {
                    fontSample("SF Pro Display (System)", font: .system(size: 24, weight: .regular))
                    fontSample("SF Pro — Semibold", font: .system(size: 24, weight: .semibold))
                    fontSample("SF Pro — Bold", font: .system(size: 24, weight: .bold))
                    fontSample("DM Serif Text", font: .dmSerif(size: 24))
                    fontSample("DM Serif Text Italic", font: .dmSerifItalic(size: 24))
                }

                Divider()
                    .padding(.vertical, 8)

                Text("Liquid Glass")
                    .font(.largeTitle.bold())
                    .foregroundStyle(Color.saturnSecondary)

                VStack(spacing: 16) {
                    Text("Card")
                        .font(.headline)
                        .foregroundStyle(Color.saturnSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 40)
                        .modifier(SaturnGlass.card)

                    HStack(spacing: 12) {
                        Text("Chip A")
                            .font(.subheadline)
                            .foregroundStyle(Color.saturnSecondary)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .modifier(SaturnGlass.chip)

                        Text("Chip B")
                            .font(.subheadline)
                            .foregroundStyle(Color.saturnSecondary)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .modifier(SaturnGlass.chip)
                    }

                    Text("Button")
                        .font(.headline.bold())
                        .foregroundStyle(Color.saturnSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .modifier(SaturnGlass.button)

                    Text("Nav Bar")
                        .font(.subheadline)
                        .foregroundStyle(Color.saturnSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .modifier(SaturnGlass.nav)
                }
            }
            .padding()
        }
        .background(Color.saturnPrimary)
    }

    private func fontSample(_ label: String, font: Font) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(font)
                .foregroundStyle(Color.saturnSecondary)
            Text(label)
                .font(.caption2)
                .foregroundStyle(Color.saturnGreyContrast)
        }
    }

    private func colorSwatch(
        _ item: (name: String, color: Color, lightHex: String, darkHex: String)
    ) -> some View {
        VStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 12)
                .fill(item.color)
                .frame(height: 80)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .strokeBorder(Color.saturnGreyAccent, lineWidth: 1)
                )

            Text(item.name)
                .font(.caption.bold())
                .foregroundStyle(Color.saturnSecondary)

            Text(colorScheme == .dark ? item.darkHex : item.lightHex)
                .font(.caption2.monospaced())
                .foregroundStyle(Color.saturnGreyContrast)
        }
    }
}

#Preview("Logged Out") {
    ContentView()
}

#Preview("Logged In") {
    ContentView()
}
