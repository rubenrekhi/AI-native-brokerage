import SwiftUI

struct AppearanceSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @AppStorage("appTheme") private var selectedTheme = AppTheme.system.rawValue
    @AppStorage("appTextSize") private var selectedTextSize = AppTextSize.small.rawValue

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            themeRow
            textSizeRow

            Spacer()
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 12 * scale)
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                }
            }
        }
        .navigationBarBackButtonHidden()
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.appearance, scale: scale, onBack: { dismiss() })
    }

    private var themeRow: some View {
        VStack(spacing: 0) {
            HStack {
                Text(L10n.Settings.theme)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.sevinoSecondary)

                Spacer()

                HStack(spacing: 4 * scale) {
                    ForEach(AppTheme.allCases) { theme in
                        Button(action: { selectedTheme = theme.rawValue }) {
                            Image(systemName: theme.icon)
                                .font(.system(size: 14 * scale, weight: .medium))
                                .foregroundStyle(
                                    selectedTheme == theme.rawValue
                                        ? Color.sevinoSecondary
                                        : Color.sevinoGreyContrast
                                )
                                .frame(width: 40 * scale, height: 40 * scale)
                        }
                        .modifier(SevinoGlass.conditionalChip(isSelected: selectedTheme == theme.rawValue))
                        .accessibilityLabel(theme.label)
                    }
                }
            }
            .padding(.vertical, 16 * scale)

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
    }

    private var textSizeRow: some View {
        VStack(spacing: 0) {
            HStack {
                Text(L10n.Settings.textSize)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.sevinoSecondary)

                Spacer()

                HStack(spacing: 4 * scale) {
                    ForEach(AppTextSize.allCases) { size in
                        Button(action: { selectedTextSize = size.rawValue }) {
                            Text(verbatim: "A")
                                .font(.system(size: size.previewSize * scale, weight: .medium))
                                .foregroundStyle(
                                    selectedTextSize == size.rawValue
                                        ? Color.sevinoSecondary
                                        : Color.sevinoGreyContrast
                                )
                                .frame(width: 40 * scale, height: 40 * scale)
                        }
                        .modifier(SevinoGlass.conditionalChip(isSelected: selectedTextSize == size.rawValue))
                        .accessibilityLabel(size.label)
                    }
                }
            }
            .padding(.vertical, 16 * scale)

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
    }
}

#Preview("Dark") {
    NavigationStack {
        AppearanceSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        AppearanceSettingsView()
    }
    .preferredColorScheme(.light)
}
