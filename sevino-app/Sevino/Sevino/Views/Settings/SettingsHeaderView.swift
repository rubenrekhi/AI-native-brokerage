import SwiftUI

struct SettingsHeaderView: View {
    let title: String
    let scale: CGFloat
    let onBack: () -> Void

    var body: some View {
        ZStack {
            Text(title)
                .font(.system(size: 20 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack {
                Button(L10n.Settings.backAccessibility, systemImage: "chevron.left", action: onBack)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)

                Spacer()
            }
        }
    }
}

#Preview("Dark") {
    ZStack {
        Color.sevinoSettingsBg.ignoresSafeArea()
        SettingsHeaderView(title: "Settings", scale: 1, onBack: {})
            .padding()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    ZStack {
        Color.sevinoSettingsBg.ignoresSafeArea()
        SettingsHeaderView(title: "Settings", scale: 1, onBack: {})
            .padding()
    }
    .preferredColorScheme(.light)
}
