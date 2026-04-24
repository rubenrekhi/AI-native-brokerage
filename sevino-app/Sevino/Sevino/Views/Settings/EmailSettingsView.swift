import SwiftUI

struct EmailSettingsView: View {
    let vm: SettingsViewModel

    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            emailCard
                .padding(.bottom, 16 * scale)

            Text(L10n.Settings.emailSupportNote)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .frame(maxWidth: .infinity, alignment: .leading)

            Spacer()
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 12 * scale)
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .navigationBarBackButtonHidden()
        .task {
            if vm.profile == nil {
                await vm.load()
            }
        }
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.email, scale: scale, onBack: { dismiss() })
    }

    private var emailCard: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(L10n.Settings.emailLabel)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(vm.displayEmail)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }
}

#if DEBUG
#Preview("Loaded") {
    NavigationStack {
        EmailSettingsView(vm: .previewLoadedForEmail())
    }
    .preferredColorScheme(.dark)
}

#Preview("Missing") {
    NavigationStack {
        EmailSettingsView(vm: SettingsViewModel(
            settingsService: PreviewStallingSettingsService(),
            fundingService: PreviewNoopFundingService()
        ))
    }
    .preferredColorScheme(.dark)
}

private extension SettingsViewModel {
    static func previewLoadedForEmail() -> SettingsViewModel {
        let vm = SettingsViewModel(
            settingsService: PreviewLoadedSettingsService(),
            fundingService: PreviewNoopFundingService()
        )
        vm.seedProfileForPreview(PreviewLoadedSettingsService.decodedProfile())
        return vm
    }
}
#endif
