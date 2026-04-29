import SwiftUI

struct AccountsSettingsView: View {
    let settingsVM: SettingsViewModel

    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    private var kycStatus: KYCStatus? {
        settingsVM.profile?.brokerage?.accountStatus
    }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            content

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
    }

    @ViewBuilder
    private var content: some View {
        if settingsVM.profile == nil, settingsVM.isLoading {
            loadingState
        } else if settingsVM.profile == nil, let error = settingsVM.error {
            errorState(message: error)
        } else {
            navLinkRow(title: L10n.Settings.brokerage, destination: .brokerage)
            navLinkRow(title: L10n.Settings.linkedAccounts, destination: .linkedAccounts)
            settingsRow(title: L10n.Settings.kycStatus, trailing: .kycBadge(kycStatus))
        }
    }

    private var loadingState: some View {
        ProgressView()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 32 * scale)
    }

    private func errorState(message: String) -> some View {
        ContentUnavailableView {
            Label(L10n.Settings.loadErrorTitle, systemImage: "exclamationmark.triangle")
        } description: {
            Text(L10n.Settings.loadErrorMessage)
        } actions: {
            Button(L10n.Settings.loadErrorRetry, action: retry)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 10 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 20 * scale))
        }
        .frame(maxWidth: .infinity)
    }

    private func retry() {
        Task { await settingsVM.reload() }
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.accounts, scale: scale, onBack: { dismiss() })
    }

    private func navLinkRow(title: String, destination: SettingsDestination) -> some View {
        NavigationLink(value: destination) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    private func settingsRow(title: String, trailing: RowTrailing) -> some View {
        Button(action: {}) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    switch trailing {
                    case .chevron:
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .accessibilityHidden(true)
                    case .kycBadge(let status):
                        if let status {
                            Text(status.label)
                                .font(.system(size: 12 * scale, weight: .semibold))
                                .foregroundStyle(status.color)
                                .padding(.horizontal, 10 * scale)
                                .padding(.vertical, 4 * scale)
                                .background(status.color.opacity(0.15), in: .rect(cornerRadius: 6 * scale))
                        } else {
                            Text(verbatim: "—")
                                .font(.system(size: 14 * scale))
                                .foregroundStyle(Color.sevinoGreyContrast)
                        }
                    }
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
        .disabled(true)
    }
}

private enum RowTrailing {
    case chevron
    case kycBadge(KYCStatus?)
}

#Preview("Dark") {
    NavigationStack {
        AccountsSettingsView(settingsVM: SettingsViewModel())
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        AccountsSettingsView(settingsVM: SettingsViewModel())
    }
    .preferredColorScheme(.light)
}
